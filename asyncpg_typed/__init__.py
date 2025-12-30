"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

__version__ = "0.1.3"
__author__ = "Levente Hunyadi"
__copyright__ = "Copyright 2025, Levente Hunyadi"
__license__ = "MIT"
__maintainer__ = "Levente Hunyadi"
__status__ = "Production"

import enum
import sys
import typing
from abc import abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import reduce
from io import StringIO
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
from types import UnionType
from typing import Any, Protocol, TypeAlias, TypeGuard, TypeVar, Union, get_args, get_origin, overload
from uuid import UUID

import asyncpg
from asyncpg.prepared_stmt import PreparedStatement

if sys.version_info < (3, 11):
    from typing_extensions import LiteralString, TypeVarTuple, Unpack
else:
    from typing import LiteralString, TypeVarTuple, Unpack

JsonType = None | bool | int | float | str | dict[str, "JsonType"] | list["JsonType"]

RequiredJsonType = bool | int | float | str | dict[str, "JsonType"] | list["JsonType"]

TargetType: TypeAlias = type[Any] | UnionType

Connection: TypeAlias = asyncpg.Connection | asyncpg.pool.PoolConnectionProxy


class TypeMismatchError(TypeError):
    "Raised when a prepared statement takes or returns a PostgreSQL type incompatible with the declared Python type."


class EnumMismatchError(TypeError):
    "Raised when a prepared statement takes or returns a PostgreSQL enum type whose permitted set of values differs from what is declared in Python."


class NoneTypeError(TypeError):
    "Raised when a column marked as required contains a `NULL` value."


if sys.version_info >= (3, 11):

    def is_enum_type(typ: Any) -> TypeGuard[type[enum.Enum]]:
        """
        `True` if the specified type is an enumeration type.
        """

        return isinstance(typ, enum.EnumType)

else:

    def is_enum_type(typ: Any) -> TypeGuard[type[enum.Enum]]:
        """
        `True` if the specified type is an enumeration type.
        """

        # use an explicit isinstance(..., type) check to filter out special forms like generics
        return isinstance(typ, type) and issubclass(typ, enum.Enum)


def is_union_type(tp: Any) -> bool:
    """
    `True` if `tp` is a union type such as `A | B` or `Union[A, B]`.
    """

    origin = get_origin(tp)
    return origin is Union or origin is UnionType


def is_optional_type(tp: Any) -> bool:
    """
    `True` if `tp` is an optional type such as `T | None`, `Optional[T]` or `Union[T, None]`.
    """

    return is_union_type(tp) and any(a is type(None) for a in get_args(tp))


def is_standard_type(tp: Any) -> bool:
    """
    `True` if the type represents a built-in or a well-known standard type.
    """

    return tp.__module__ == "builtins" or tp.__module__ == UnionType.__module__


def is_json_type(tp: Any) -> bool:
    """
    `True` if the type represents an object de-serialized from a JSON string.
    """

    return tp in [JsonType, RequiredJsonType]


def is_inet_type(tp: Any) -> bool:
    """
    `True` if the type represents an IP address or network.
    """

    return tp in [IPv4Address, IPv6Address, IPv4Network, IPv6Network]


def make_union_type(tpl: list[Any]) -> UnionType:
    """
    Creates a `UnionType` (a.k.a. `A | B | C`) dynamically at run time.
    """

    if len(tpl) < 2:
        raise ValueError("expected: at least two types to make a `UnionType`")

    return reduce(lambda a, b: a | b, tpl)


def get_required_type(tp: Any) -> Any:
    """
    Removes `None` from an optional type (i.e. a union type that has `None` as a member).
    """

    if not is_optional_type(tp):
        return tp

    tpl = [a for a in get_args(tp) if a is not type(None)]
    if len(tpl) > 1:
        return make_union_type(tpl)
    elif len(tpl) > 0:
        return tpl[0]
    else:
        return type(None)


def _standard_json_decoder() -> Callable[[str], JsonType]:
    import json

    _json_decoder = json.JSONDecoder()
    return _json_decoder.decode


def _json_decoder() -> Callable[[str], JsonType]:
    if typing.TYPE_CHECKING:
        return _standard_json_decoder()
    else:
        try:
            import orjson

            return orjson.loads
        except ModuleNotFoundError:
            return _standard_json_decoder()


JSON_DECODER = _json_decoder()


def _standard_json_encoder() -> Callable[[JsonType], str]:
    import json

    _json_encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return _json_encoder.encode


def _json_encoder() -> Callable[[JsonType], str]:
    if typing.TYPE_CHECKING:
        return _standard_json_encoder()
    else:
        try:
            import orjson

            def _wrap(value: JsonType) -> str:
                return orjson.dumps(value).decode()

            return _wrap
        except ModuleNotFoundError:
            return _standard_json_encoder()


JSON_ENCODER = _json_encoder()


def get_output_converter_for(tp: Any) -> Callable[[Any], Any]:
    """
    Returns a callable that takes a wire type and returns a target type.

    A wire type is one of the types returned by asyncpg.
    A target type is one of the types supported by the library.
    """

    if is_json_type(tp):
        # asyncpg returns fields of type `json` and `jsonb` as `str`, which must be de-serialized
        return JSON_DECODER
    else:
        # target data types that require conversion must have a single-argument `__init__` that takes an object of the source type
        return tp


def get_input_converter_for(tp: Any) -> Callable[[Any], Any]:
    """
    Returns a callable that takes a source type and returns a wire type.

    A source type is one of the types supported by the library.
    A wire type is one of the types returned by asyncpg.
    """

    if is_json_type(tp):
        # asyncpg expects fields of type `json` and `jsonb` as `str`, which must be serialized
        return JSON_ENCODER
    else:
        # source data types that require conversion must have a single-argument `__init__` that takes an object of the source type
        return tp


# maps PostgreSQL internal type names to compatible Python types
_NAME_TO_TYPE: dict[str, tuple[Any, ...]] = {
    # boolean type
    "bool": (bool,),
    # numeric types
    "int2": (int,),
    "int4": (int,),
    "int8": (int,),
    "float4": (float,),
    "float8": (float,),
    "numeric": (Decimal,),
    # date and time types
    "date": (date,),
    "time": (time,),
    "timetz": (time,),
    "timestamp": (datetime,),
    "timestamptz": (datetime,),
    "interval": (timedelta,),
    # character sequence types
    "bpchar": (str,),
    "varchar": (str,),
    "text": (str,),
    # binary sequence types
    "bytea": (bytes,),
    # unique identifier type
    "uuid": (UUID,),
    # address types
    "cidr": (IPv4Network, IPv6Network, IPv4Network | IPv6Network),
    "inet": (IPv4Network, IPv6Network, IPv4Network | IPv6Network, IPv4Address, IPv6Address, IPv4Address | IPv6Address),
    "macaddr": (str,),
    "macaddr8": (str,),
    # JSON type
    "json": (str, RequiredJsonType),
    "jsonb": (str, RequiredJsonType),
    # XML type
    "xml": (str,),
    # geometric types
    "point": (asyncpg.Point,),
    "line": (asyncpg.Line,),
    "lseg": (asyncpg.LineSegment,),
    "box": (asyncpg.Box,),
    "path": (asyncpg.Path,),
    "polygon": (asyncpg.Polygon,),
    "circle": (asyncpg.Circle,),
    # range types
    "int4range": (asyncpg.Range[int],),
    "int4multirange": (list[asyncpg.Range[int]],),
    "int8range": (asyncpg.Range[int],),
    "int8multirange": (list[asyncpg.Range[int]],),
    "numrange": (asyncpg.Range[Decimal],),
    "nummultirange": (list[asyncpg.Range[Decimal]],),
    "tsrange": (asyncpg.Range[datetime],),
    "tsmultirange": (list[asyncpg.Range[datetime]],),
    "tstzrange": (asyncpg.Range[datetime],),
    "tstzmultirange": (list[asyncpg.Range[datetime]],),
    "daterange": (asyncpg.Range[date],),
    "datemultirange": (list[asyncpg.Range[date]],),
}


def type_to_str(tp: Any) -> str:
    "Emits a friendly name for a type."

    if isinstance(tp, type):
        return tp.__name__
    else:
        return str(tp)


class _TypeVerifier:
    """
    Verifies if the Python target type can represent the PostgreSQL source type.
    """

    _connection: Connection

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    async def _check_enum_type(self, pg_name: str, pg_type: asyncpg.Type, data_type: type[enum.Enum]) -> None:
        """
        Verifies if a Python enumeration type matches a PostgreSQL enumeration type.
        """

        for e in data_type:
            if not isinstance(e.value, str):
                raise TypeMismatchError(f"expected: Python enum type `{type_to_str(data_type)}` with `str` values; got: `{type_to_str(type(e.value))}` for enum field `{e.name}`")

        py_values = set(e.value for e in data_type)

        rows = await self._connection.fetch("SELECT enumlabel FROM pg_enum WHERE enumtypid = $1 ORDER BY enumsortorder;", pg_type.oid)
        db_values = set(row[0] for row in rows)

        db_extra = db_values - py_values
        if db_extra:
            raise EnumMismatchError(f"expected: Python enum type `{type_to_str(data_type)}` to match values of PostgreSQL enum type `{pg_type.name}` for {pg_name}; missing value(s): {', '.join(f'`{val}`' for val in db_extra)})")

        py_extra = py_values - db_values
        if py_extra:
            raise EnumMismatchError(f"expected: Python enum type `{type_to_str(data_type)}` to match values of PostgreSQL enum type `{pg_type.name}` for {pg_name}; got extra value(s): {', '.join(f'`{val}`' for val in py_extra)})")

    async def check_data_type(self, pg_name: str, pg_type: asyncpg.Type, data_type: TargetType) -> None:
        """
        Verifies if the Python target type can represent the PostgreSQL source type.
        """

        if pg_type.schema == "pg_catalog":  # well-known PostgreSQL types
            if is_enum_type(data_type):
                if pg_type.name not in ["bpchar", "varchar", "text"]:
                    raise TypeMismatchError(f"expected: Python enum type `{type_to_str(data_type)}` for {pg_name}; got: PostgreSQL type `{pg_type.kind}` of `{pg_type.name}` instead of `char`, `varchar` or `text`")
            else:
                expected_types = _NAME_TO_TYPE.get(pg_type.name)
                if expected_types is None:
                    raise TypeMismatchError(f"expected: Python type `{type_to_str(data_type)}` for {pg_name}; got: unrecognized PostgreSQL type `{pg_type.kind}` of `{pg_type.name}`")
                elif data_type not in expected_types:
                    raise TypeMismatchError(
                        f"expected: Python type `{type_to_str(data_type)}` for {pg_name}; "
                        f"got: incompatible PostgreSQL type `{pg_type.kind}` of `{pg_type.name}`, which converts to one of the Python types {', '.join(f'`{type_to_str(tp)}`' for tp in expected_types)}"
                    )
        elif pg_type.kind == "composite":  # PostgreSQL composite types
            # user-defined composite types registered with `conn.set_type_codec()` typically using `format="tuple"`
            pass
        else:  # custom PostgreSQL types
            if is_enum_type(data_type):
                await self._check_enum_type(pg_name, pg_type, data_type)
            elif is_standard_type(data_type):
                raise TypeMismatchError(f"expected: Python type `{type_to_str(data_type)}` for {pg_name}; got: PostgreSQL type `{pg_type.kind}` of `{pg_type.name}`")
            else:
                # user-defined types registered with `conn.set_type_codec()`
                pass


@dataclass(frozen=True)
class _SQLPlaceholder:
    ordinal: int
    data_type: TargetType

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.ordinal}, {self.data_type!r})"


class _SQLObject:
    """
    Associates input and output type information with a SQL statement.
    """

    _parameter_data_types: tuple[_SQLPlaceholder, ...]
    _resultset_data_types: tuple[TargetType, ...]
    _parameter_cast: int
    _parameter_converters: tuple[Callable[[Any], Any], ...]
    _required: int
    _resultset_cast: int
    _resultset_converters: tuple[Callable[[Any], Any], ...]

    @property
    def parameter_data_types(self) -> tuple[_SQLPlaceholder, ...]:
        return self._parameter_data_types

    @property
    def resultset_data_types(self) -> tuple[TargetType, ...]:
        return self._resultset_data_types

    def __init__(
        self,
        input_data_types: tuple[TargetType, ...],
        output_data_types: tuple[TargetType, ...],
    ) -> None:
        self._parameter_data_types = tuple(_SQLPlaceholder(ordinal, get_required_type(arg)) for ordinal, arg in enumerate(input_data_types, start=1))
        self._resultset_data_types = tuple(get_required_type(data_type) for data_type in output_data_types)

        # create a bit-field of types that require cast or serialization (1: apply conversion; 0: forward value as-is)
        parameter_cast = 0
        for index, placeholder in enumerate(self._parameter_data_types):
            parameter_cast |= is_json_type(placeholder.data_type) << index
        self._parameter_cast = parameter_cast

        self._parameter_converters = tuple(get_input_converter_for(placeholder.data_type) for placeholder in self._parameter_data_types)

        # create a bit-field of required types (1: required; 0: optional)
        required = 0
        for index, data_type in enumerate(output_data_types):
            required |= (not is_optional_type(data_type)) << index
        self._required = required

        # create a bit-field of types that require cast or de-serialization (1: apply conversion; 0: forward value as-is)
        resultset_cast = 0
        for index, data_type in enumerate(self._resultset_data_types):
            resultset_cast |= (is_enum_type(data_type) or is_json_type(data_type) or is_inet_type(data_type)) << index
        self._resultset_cast = resultset_cast

        self._resultset_converters = tuple(get_output_converter_for(data_type) for data_type in self._resultset_data_types)

    def _raise_required_is_none(self, row: tuple[Any, ...], row_index: int | None = None) -> None:
        """
        Raises an error with the index of the first column value that is of a required type but has been assigned a value of `None`.
        """

        for col_index in range(len(row)):
            if (self._required >> col_index & 1) and row[col_index] is None:
                if row_index is not None:
                    row_col_spec = f"row #{row_index} and column #{col_index}"
                else:
                    row_col_spec = f"column #{col_index}"
                raise NoneTypeError(f"expected: {self._resultset_data_types[col_index]} in {row_col_spec}; got: NULL")

    def check_rows(self, rows: list[tuple[Any, ...]]) -> None:
        """
        Verifies if declared types match actual value types in a resultset.
        """

        if not rows:
            return

        required = self._required
        if not required:
            return

        match len(rows[0]):
            case 1:
                for r, row in enumerate(rows):
                    if required & (row[0] is None):
                        self._raise_required_is_none(row, r)
            case 2:
                for r, row in enumerate(rows):
                    a, b = row
                    if required & ((a is None) | (b is None) << 1):
                        self._raise_required_is_none(row, r)
            case 3:
                for r, row in enumerate(rows):
                    a, b, c = row
                    if required & ((a is None) | (b is None) << 1 | (c is None) << 2):
                        self._raise_required_is_none(row, r)
            case 4:
                for r, row in enumerate(rows):
                    a, b, c, d = row
                    if required & ((a is None) | (b is None) << 1 | (c is None) << 2 | (d is None) << 3):
                        self._raise_required_is_none(row, r)
            case 5:
                for r, row in enumerate(rows):
                    a, b, c, d, e = row
                    if required & ((a is None) | (b is None) << 1 | (c is None) << 2 | (d is None) << 3 | (e is None) << 4):
                        self._raise_required_is_none(row, r)
            case 6:
                for r, row in enumerate(rows):
                    a, b, c, d, e, f = row
                    if required & ((a is None) | (b is None) << 1 | (c is None) << 2 | (d is None) << 3 | (e is None) << 4 | (f is None) << 5):
                        self._raise_required_is_none(row, r)
            case 7:
                for r, row in enumerate(rows):
                    a, b, c, d, e, f, g = row
                    if required & ((a is None) | (b is None) << 1 | (c is None) << 2 | (d is None) << 3 | (e is None) << 4 | (f is None) << 5 | (g is None) << 6):
                        self._raise_required_is_none(row, r)
            case 8:
                for r, row in enumerate(rows):
                    a, b, c, d, e, f, g, h = row
                    if required & ((a is None) | (b is None) << 1 | (c is None) << 2 | (d is None) << 3 | (e is None) << 4 | (f is None) << 5 | (g is None) << 6 | (h is None) << 7):
                        self._raise_required_is_none(row, r)
            case _:
                for r, row in enumerate(rows):
                    self._raise_required_is_none(row, r)

    def check_row(self, row: tuple[Any, ...]) -> None:
        """
        Verifies if declared types match actual value types in a single row.
        """

        required = self._required
        if not required:
            return

        match len(row):
            case 1:
                if required & (row[0] is None):
                    self._raise_required_is_none(row)
            case 2:
                a, b = row
                if required & ((a is None) | (b is None) << 1):
                    self._raise_required_is_none(row)
            case 3:
                a, b, c = row
                if required & ((a is None) | (b is None) << 1 | (c is None) << 2):
                    self._raise_required_is_none(row)
            case 4:
                a, b, c, d = row
                if required & ((a is None) | (b is None) << 1 | (c is None) << 2 | (d is None) << 3):
                    self._raise_required_is_none(row)
            case 5:
                a, b, c, d, e = row
                if required & ((a is None) | (b is None) << 1 | (c is None) << 2 | (d is None) << 3 | (e is None) << 4):
                    self._raise_required_is_none(row)
            case 6:
                a, b, c, d, e, f = row
                if required & ((a is None) | (b is None) << 1 | (c is None) << 2 | (d is None) << 3 | (e is None) << 4 | (f is None) << 5):
                    self._raise_required_is_none(row)
            case 7:
                a, b, c, d, e, f, g = row
                if required & ((a is None) | (b is None) << 1 | (c is None) << 2 | (d is None) << 3 | (e is None) << 4 | (f is None) << 5 | (g is None) << 6):
                    self._raise_required_is_none(row)
            case 8:
                a, b, c, d, e, f, g, h = row
                if required & ((a is None) | (b is None) << 1 | (c is None) << 2 | (d is None) << 3 | (e is None) << 4 | (f is None) << 5 | (g is None) << 6 | (h is None) << 7):
                    self._raise_required_is_none(row)
            case _:
                self._raise_required_is_none(row)

    def check_value(self, value: Any) -> None:
        """
        Verifies if the declared type matches the actual value type.
        """

        if self._required and value is None:
            raise NoneTypeError(f"expected: {self._resultset_data_types[0]}; got: NULL")

    def convert_arg_lists(self, arg_lists: Iterable[Sequence[Any]]) -> Iterable[Sequence[Any]]:
        """
        Converts a list of Python query argument tuples to a list of PostgreSQL parameter tuples.
        """

        cast = self._parameter_cast
        if cast:
            converters = self._parameter_converters
            yield from (tuple((converters[i](value) if (value := arg[i]) is not None and cast >> i & 1 else value) for i in range(len(arg))) for arg in arg_lists)
        else:
            yield from arg_lists

    def convert_arg_list(self, arg_list: Sequence[Any]) -> Sequence[Any]:
        """
        Converts Python query arguments to PostgreSQL parameters.
        """

        cast = self._parameter_cast
        if cast:
            converters = self._parameter_converters
            return tuple((converters[i](value) if (value := arg_list[i]) is not None and cast >> i & 1 else value) for i in range(len(arg_list)))
        else:
            return tuple(value for value in arg_list)

    def convert_rows(self, rows: list[asyncpg.Record]) -> list[tuple[Any, ...]]:
        """
        Converts columns in the PostgreSQL result-set to their corresponding Python target types.

        :param rows: List of rows returned by PostgreSQL.
        :returns: List of tuples with each tuple element having the configured Python target type.
        """

        cast = self._resultset_cast
        if cast:
            converters = self._resultset_converters
            return [tuple((converters[i](value) if (value := row[i]) is not None and cast >> i & 1 else value) for i in range(len(row))) for row in rows]
        else:
            return [tuple(value for value in row) for row in rows]

    def convert_row(self, row: asyncpg.Record) -> tuple[Any, ...]:
        """
        Converts columns in the PostgreSQL result-set to their corresponding Python target types.

        :param row: A single row returned by PostgreSQL.
        :returns: A tuple with each tuple element having the configured Python target type.
        """

        cast = self._resultset_cast
        if cast:
            converters = self._resultset_converters
            return tuple((converters[i](value) if (value := row[i]) is not None and cast >> i & 1 else value) for i in range(len(row)))
        else:
            return tuple(value for value in row)

    def convert_value(self, value: Any) -> Any:
        """
        Converts a single PostgreSQL value to its corresponding Python target type.

        :param value: A single value returned by PostgreSQL.
        :returns: A converted value having the configured Python target type.
        """

        return self._resultset_converters[0](value) if value is not None and self._resultset_cast else value

    @abstractmethod
    def query(self) -> str:
        """
        Returns a SQL query string with PostgreSQL ordinal placeholders.
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.query()!r})"

    def __str__(self) -> str:
        return self.query()


if sys.version_info >= (3, 14):
    from string.templatelib import Interpolation, Template  # type: ignore[import-not-found]

    SQLExpression: TypeAlias = Template | LiteralString

    class _SQLTemplate(_SQLObject):
        """
        A SQL query specified with the Python t-string syntax.
        """

        _strings: tuple[str, ...]
        _placeholders: tuple[_SQLPlaceholder, ...]

        def __init__(
            self,
            template: Template,
            *,
            args: tuple[TargetType, ...],
            resultset: tuple[TargetType, ...],
        ) -> None:
            super().__init__(args, resultset)

            for ip in template.interpolations:
                if ip.conversion is not None:
                    raise TypeError(f"interpolation `{ip.expression}` expected to apply no conversion")
                if ip.format_spec:
                    raise TypeError(f"interpolation `{ip.expression}` expected to apply no format spec")
                if not isinstance(ip.value, int):
                    raise TypeError(f"interpolation `{ip.expression}` expected to evaluate to an integer")

            self._strings = template.strings

            if len(self.parameter_data_types) > 0:

                def _to_placeholder(ip: Interpolation) -> _SQLPlaceholder:
                    ordinal = int(ip.value)
                    if not (0 < ordinal <= len(self.parameter_data_types)):
                        raise IndexError(f"interpolation `{ip.expression}` is an ordinal out of range; expected: 0 < value <= {len(self.parameter_data_types)}")
                    return self.parameter_data_types[int(ip.value) - 1]

                self._placeholders = tuple(_to_placeholder(ip) for ip in template.interpolations)
            else:
                self._placeholders = ()

        def query(self) -> str:
            buf = StringIO()
            for s, p in zip(self._strings[:-1], self._placeholders, strict=True):
                buf.write(s)
                buf.write(f"${p.ordinal}")
            buf.write(self._strings[-1])
            return buf.getvalue()

else:
    SQLExpression = LiteralString


class _SQLString(_SQLObject):
    """
    A SQL query specified as a plain string (e.g. f-string).
    """

    _sql: str

    def __init__(
        self,
        sql: str,
        *,
        args: tuple[TargetType, ...],
        resultset: tuple[TargetType, ...],
    ) -> None:
        super().__init__(args, resultset)
        self._sql = sql

    def query(self) -> str:
        return self._sql


class _SQL(Protocol):
    """
    Represents a SQL statement with associated type information.
    """


class _SQLImpl(_SQL):
    """
    Forwards input data to an `asyncpg.PreparedStatement`, and validates output data (if necessary).
    """

    _sql: _SQLObject

    def __init__(self, sql: _SQLObject) -> None:
        self._sql = sql

    def __str__(self) -> str:
        return str(self._sql)

    def __repr__(self) -> str:
        return repr(self._sql)

    async def _prepare(self, connection: Connection) -> PreparedStatement:
        stmt = await connection.prepare(self._sql.query())

        verifier = _TypeVerifier(connection)
        for param, placeholder in zip(stmt.get_parameters(), self._sql.parameter_data_types, strict=True):
            await verifier.check_data_type(f"parameter ${placeholder.ordinal}", param, placeholder.data_type)
        for attr, data_type in zip(stmt.get_attributes(), self._sql.resultset_data_types, strict=True):
            await verifier.check_data_type(f"column `{attr.name}`", attr.type, data_type)

        return stmt

    async def execute(self, connection: asyncpg.Connection, *args: Any) -> None:
        await connection.execute(self._sql.query(), *self._sql.convert_arg_list(args))

    async def executemany(self, connection: asyncpg.Connection, args: Iterable[Sequence[Any]]) -> None:
        stmt = await self._prepare(connection)
        await stmt.executemany(self._sql.convert_arg_lists(args))

    def _cast_fetch(self, rows: list[asyncpg.Record]) -> list[tuple[Any, ...]]:
        resultset = self._sql.convert_rows(rows)
        self._sql.check_rows(resultset)
        return resultset

    async def fetch(self, connection: asyncpg.Connection, *args: Any) -> list[tuple[Any, ...]]:
        stmt = await self._prepare(connection)
        rows = await stmt.fetch(*self._sql.convert_arg_list(args))
        return self._cast_fetch(rows)

    async def fetchmany(self, connection: asyncpg.Connection, args: Iterable[Sequence[Any]]) -> list[tuple[Any, ...]]:
        stmt = await self._prepare(connection)
        rows = await stmt.fetchmany(self._sql.convert_arg_lists(args))
        return self._cast_fetch(rows)

    async def fetchrow(self, connection: asyncpg.Connection, *args: Any) -> tuple[Any, ...] | None:
        stmt = await self._prepare(connection)
        row = await stmt.fetchrow(*self._sql.convert_arg_list(args))
        if row is None:
            return None
        resultset = self._sql.convert_row(row)
        self._sql.check_row(resultset)
        return resultset

    async def fetchval(self, connection: asyncpg.Connection, *args: Any) -> Any:
        stmt = await self._prepare(connection)
        value = await stmt.fetchval(*self._sql.convert_arg_list(args))
        result = self._sql.convert_value(value)
        self._sql.check_value(result)
        return result


P1 = TypeVar("P1")
PX = TypeVarTuple("PX")

RT = TypeVar("RT")
R1 = TypeVar("R1")
R2 = TypeVar("R2")
RX = TypeVarTuple("RX")


### START OF AUTO-GENERATED BLOCK FOR Protocol ###
class SQL_P0(Protocol):
    @abstractmethod
    async def execute(self, connection: Connection) -> None: ...


class SQL_R1_P0(SQL_P0, Protocol[R1]):
    @abstractmethod
    async def fetch(self, connection: Connection) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection) -> tuple[R1] | None: ...
    @abstractmethod
    async def fetchval(self, connection: Connection) -> R1: ...


class SQL_RX_P0(SQL_P0, Protocol[RT]):
    @abstractmethod
    async def fetch(self, connection: Connection) -> list[RT]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection) -> RT | None: ...


class SQL_PX(Protocol[Unpack[PX]]):
    @abstractmethod
    async def execute(self, connection: Connection, *args: Unpack[PX]) -> None: ...
    @abstractmethod
    async def executemany(self, connection: Connection, args: Iterable[tuple[Unpack[PX]]]) -> None: ...


class SQL_R1_PX(SQL_PX[Unpack[PX]], Protocol[R1, Unpack[PX]]):
    @abstractmethod
    async def fetch(self, connection: Connection, *args: Unpack[PX]) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[Unpack[PX]]]) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, *args: Unpack[PX]) -> tuple[R1] | None: ...
    @abstractmethod
    async def fetchval(self, connection: Connection, *args: Unpack[PX]) -> R1: ...


class SQL_RX_PX(SQL_PX[Unpack[PX]], Protocol[RT, Unpack[PX]]):
    @abstractmethod
    async def fetch(self, connection: Connection, *args: Unpack[PX]) -> list[RT]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[Unpack[PX]]]) -> list[RT]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, *args: Unpack[PX]) -> RT | None: ...


### END OF AUTO-GENERATED BLOCK FOR Protocol ###


class SQLFactory:
    """
    Creates type-safe SQL queries.
    """

    ### START OF AUTO-GENERATED BLOCK FOR sql ###
    @overload
    def sql(self, stmt: SQLExpression) -> SQL_P0: ...
    @overload
    def sql(self, stmt: SQLExpression, *, result: type[R1]) -> SQL_R1_P0[R1]: ...
    @overload
    def sql(self, stmt: SQLExpression, *, resultset: type[tuple[R1]]) -> SQL_R1_P0[R1]: ...
    @overload
    def sql(self, stmt: SQLExpression, *, resultset: type[tuple[R1, R2, Unpack[RX]]]) -> SQL_RX_P0[tuple[R1, R2, Unpack[RX]]]: ...
    @overload
    def sql(self, stmt: SQLExpression, *, arg: type[P1]) -> SQL_PX[P1]: ...
    @overload
    def sql(self, stmt: SQLExpression, *, arg: type[P1], result: type[R1]) -> SQL_R1_PX[R1, P1]: ...
    @overload
    def sql(self, stmt: SQLExpression, *, arg: type[P1], resultset: type[tuple[R1]]) -> SQL_R1_PX[R1, P1]: ...
    @overload
    def sql(self, stmt: SQLExpression, *, arg: type[P1], resultset: type[tuple[R1, R2, Unpack[RX]]]) -> SQL_RX_PX[tuple[R1, R2, Unpack[RX]], P1]: ...
    @overload
    def sql(self, stmt: SQLExpression, *, args: type[tuple[P1, Unpack[PX]]]) -> SQL_PX[P1, Unpack[PX]]: ...
    @overload
    def sql(self, stmt: SQLExpression, *, args: type[tuple[P1, Unpack[PX]]], result: type[R1]) -> SQL_R1_PX[R1, P1, Unpack[PX]]: ...
    @overload
    def sql(self, stmt: SQLExpression, *, args: type[tuple[P1, Unpack[PX]]], resultset: type[tuple[R1]]) -> SQL_R1_PX[R1, P1, Unpack[PX]]: ...
    @overload
    def sql(self, stmt: SQLExpression, *, args: type[tuple[P1, Unpack[PX]]], resultset: type[tuple[R1, R2, Unpack[RX]]]) -> SQL_RX_PX[tuple[R1, R2, Unpack[RX]], P1, Unpack[PX]]: ...

    ### END OF AUTO-GENERATED BLOCK FOR sql ###

    def sql(self, stmt: SQLExpression, *, args: type[Any] | None = None, resultset: type[Any] | None = None, arg: type[Any] | None = None, result: type[Any] | None = None) -> _SQL:
        """
        Creates a SQL statement with associated type information.

        :param stmt: SQL statement as a literal string or template.
        :param args: Type signature for multiple input parameters (e.g. `tuple[bool, int, str]`).
        :param resultset: Type signature for multiple resultset columns (e.g. `tuple[datetime, Decimal, str]`).
        :param arg: Type signature for a single input parameter (e.g. `int`).
        :param result: Type signature for a single result column (e.g. `UUID`).
        """

        input_data_types, output_data_types = _sql_args_resultset(args=args, resultset=resultset, arg=arg, result=result)

        obj: _SQLObject
        if sys.version_info >= (3, 14):
            match stmt:
                case Template():
                    obj = _SQLTemplate(stmt, args=input_data_types, resultset=output_data_types)
                case str():
                    obj = _SQLString(stmt, args=input_data_types, resultset=output_data_types)
        else:
            obj = _SQLString(stmt, args=input_data_types, resultset=output_data_types)

        return _SQLImpl(obj)

    ### START OF AUTO-GENERATED BLOCK FOR unsafe_sql ###
    @overload
    def unsafe_sql(self, stmt: str) -> SQL_P0: ...
    @overload
    def unsafe_sql(self, stmt: str, *, result: type[R1]) -> SQL_R1_P0[R1]: ...
    @overload
    def unsafe_sql(self, stmt: str, *, resultset: type[tuple[R1]]) -> SQL_R1_P0[R1]: ...
    @overload
    def unsafe_sql(self, stmt: str, *, resultset: type[tuple[R1, R2, Unpack[RX]]]) -> SQL_RX_P0[tuple[R1, R2, Unpack[RX]]]: ...
    @overload
    def unsafe_sql(self, stmt: str, *, arg: type[P1]) -> SQL_PX[P1]: ...
    @overload
    def unsafe_sql(self, stmt: str, *, arg: type[P1], result: type[R1]) -> SQL_R1_PX[R1, P1]: ...
    @overload
    def unsafe_sql(self, stmt: str, *, arg: type[P1], resultset: type[tuple[R1]]) -> SQL_R1_PX[R1, P1]: ...
    @overload
    def unsafe_sql(self, stmt: str, *, arg: type[P1], resultset: type[tuple[R1, R2, Unpack[RX]]]) -> SQL_RX_PX[tuple[R1, R2, Unpack[RX]], P1]: ...
    @overload
    def unsafe_sql(self, stmt: str, *, args: type[tuple[P1, Unpack[PX]]]) -> SQL_PX[P1, Unpack[PX]]: ...
    @overload
    def unsafe_sql(self, stmt: str, *, args: type[tuple[P1, Unpack[PX]]], result: type[R1]) -> SQL_R1_PX[R1, P1, Unpack[PX]]: ...
    @overload
    def unsafe_sql(self, stmt: str, *, args: type[tuple[P1, Unpack[PX]]], resultset: type[tuple[R1]]) -> SQL_R1_PX[R1, P1, Unpack[PX]]: ...
    @overload
    def unsafe_sql(self, stmt: str, *, args: type[tuple[P1, Unpack[PX]]], resultset: type[tuple[R1, R2, Unpack[RX]]]) -> SQL_RX_PX[tuple[R1, R2, Unpack[RX]], P1, Unpack[PX]]: ...

    ### END OF AUTO-GENERATED BLOCK FOR unsafe_sql ###

    def unsafe_sql(self, stmt: str, *, args: type[Any] | None = None, resultset: type[Any] | None = None, arg: type[Any] | None = None, result: type[Any] | None = None) -> _SQL:
        """
        Creates a SQL statement with associated type information from a string.

        This offers an alternative to the function :func:`sql` when we want to prevent the type checker from enforcing
        a string literal, e.g. when we want to embed a variable as the table name to dynamically create a SQL statement.

        :param stmt: SQL statement as a string (or f-string).
        :param args: Type signature for multiple input parameters (e.g. `tuple[bool, int, str]`).
        :param resultset: Type signature for multiple resultset columns (e.g. `tuple[datetime, Decimal, str]`).
        :param arg: Type signature for a single input parameter (e.g. `int`).
        :param result: Type signature for a single result column (e.g. `UUID`).
        """

        input_data_types, output_data_types = _sql_args_resultset(args=args, resultset=resultset, arg=arg, result=result)
        obj = _SQLString(stmt, args=input_data_types, resultset=output_data_types)
        return _SQLImpl(obj)


def _sql_args_resultset(*, args: type[Any] | None = None, resultset: type[Any] | None = None, arg: type[Any] | None = None, result: type[Any] | None = None) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    "Parses an argument/resultset signature into input/output types."

    if args is not None and arg is not None:
        raise TypeError("expected: either `args` or `arg`; got: both")
    if resultset is not None and result is not None:
        raise TypeError("expected: either `resultset` or `result`; got: both")

    if args is not None:
        if get_origin(args) is not tuple:
            raise TypeError(f"expected: `type[tuple[T, ...]]` for `args`; got: {type(args)}")
        input_data_types = get_args(args)
    elif arg is not None:
        input_data_types = (arg,)
    else:
        input_data_types = ()

    if resultset is not None:
        if get_origin(resultset) is not tuple:
            raise TypeError(f"expected: `type[tuple[T, ...]]` for `resultset`; got: {type(resultset)}")
        output_data_types = get_args(resultset)
    elif result is not None:
        output_data_types = (result,)
    else:
        output_data_types = ()

    return input_data_types, output_data_types


FACTORY: SQLFactory = SQLFactory()

sql = FACTORY.sql
unsafe_sql = FACTORY.unsafe_sql
