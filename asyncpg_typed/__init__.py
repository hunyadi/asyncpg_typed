"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

__version__ = "0.1.0"
__author__ = "Levente Hunyadi"
__copyright__ = "Copyright 2025, Levente Hunyadi"
__license__ = "MIT"
__maintainer__ = "Levente Hunyadi"
__status__ = "Production"

import sys
import typing
from abc import abstractmethod
from collections.abc import Iterable, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from functools import reduce
from io import StringIO
from types import UnionType
from typing import Any, Generic, NoReturn, TypeAlias, TypeVar, Union, get_args, get_origin, overload
from uuid import UUID

import asyncpg
from asyncpg.prepared_stmt import PreparedStatement

# list of supported data types
DATA_TYPES: list[type[Any]] = [bool, int, float, Decimal, date, time, datetime, str, bytes, UUID]

# maximum number of inbound query parameters
NUM_ARGS = 8

# maximum number of outbound resultset columns
NUM_RESULTS = 8


def is_union_type(tp: Any) -> bool:
    """
    Returns `True` if `tp` is a union type such as `A | B` or `Union[A, B]`.
    """

    origin = get_origin(tp)
    return origin is Union or origin is UnionType


def is_optional_type(tp: Any) -> bool:
    """
    Returns `True` if `tp` is an optional type such as `T | None`, `Optional[T]` or `Union[T, None]`.
    """

    return is_union_type(tp) and any(a is type(None) for a in get_args(tp))


def is_standard_type(tp: Any) -> bool:
    """
    Returns `True` if the type represents a built-in or a well-known standard type.
    """

    return tp.__module__ == "builtins" or tp.__module__ == UnionType.__module__


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


# maps PostgreSQL internal type names to Python types
_name_to_type: dict[str, Any] = {
    "bool": bool,
    "int2": int,
    "int4": int,
    "int8": int,
    "float4": float,
    "float8": float,
    "numeric": Decimal,
    "date": date,
    "time": time,
    "timetz": time,
    "timestamp": datetime,
    "timestamptz": datetime,
    "bpchar": str,
    "varchar": str,
    "text": str,
    "bytea": bytes,
    "json": str,
    "jsonb": str,
    "uuid": UUID,
}


def check_data_type(name: str, data_type: type[Any]) -> bool:
    """
    Verifies if the Python target type can represent the PostgreSQL source type.
    """

    expected_type = _name_to_type.get(name)
    required_type = get_required_type(data_type)

    if expected_type is not None:
        return expected_type == required_type
    if is_standard_type(required_type):
        return False

    # user-defined type registered with `conn.set_type_codec()`
    return True


class _SQLPlaceholder:
    ordinal: int
    data_type: type[Any]

    def __init__(self, ordinal: int, data_type: type[Any]) -> None:
        self.ordinal = ordinal
        self.data_type = data_type

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.ordinal}, {self.data_type!r})"


class _SQLObject:
    """
    Associates input and output type information with a SQL statement.
    """

    parameter_data_types: tuple[_SQLPlaceholder, ...]
    resultset_data_types: tuple[type[Any], ...]
    required: int

    def __init__(
        self,
        *,
        args: type[Any] | None = None,
        resultset: type[Any] | None = None,
    ) -> None:
        if args is not None:
            if get_origin(args) is tuple:
                self.parameter_data_types = tuple(_SQLPlaceholder(ordinal, arg) for ordinal, arg in enumerate(get_args(args), start=1))
            else:
                self.parameter_data_types = (_SQLPlaceholder(1, args),)
        else:
            self.parameter_data_types = ()

        if resultset is not None:
            if get_origin(resultset) is tuple:
                self.resultset_data_types = get_args(resultset)
            else:
                self.resultset_data_types = (resultset,)
        else:
            self.resultset_data_types = ()

        # create a bit-field of required types (1: required; 0: optional)
        required = 0
        for index, data_type in enumerate(self.resultset_data_types):
            required |= (not is_optional_type(data_type)) << index
        self.required = required

    def _raise_required_is_none(self, row: tuple[Any, ...], row_index: int | None = None) -> NoReturn:
        """
        Raises an error with the index of the first column value that is of a required type but has been assigned a value of `None`.
        """

        for col_index in range(len(row)):
            if (self.required >> col_index & 1) and row[col_index] is None:
                if row_index is not None:
                    row_col_spec = f"row #{row_index} and column #{col_index}"
                else:
                    row_col_spec = f"column #{col_index}"
                raise TypeError(f"expected: {self.resultset_data_types[col_index]} in {row_col_spec}; got: NULL")

        raise NotImplementedError("unexpected code path")

    def check_rows(self, rows: list[tuple[Any, ...]]) -> None:
        """
        Verifies if declared types match actual value types in a resultset.
        """

        if not rows:
            return

        required = self.required
        if not required:
            return

        assert NUM_RESULTS <= 8

        match len(rows[0]):
            case 1:
                for r, row in enumerate(rows):
                    if required & (row[0] is None):
                        self._raise_required_is_none(row, r)
            case 2:
                for r, row in enumerate(rows):
                    if required & ((row[0] is None) | (row[1] is None) << 1):
                        self._raise_required_is_none(row, r)
            case 3:
                for r, row in enumerate(rows):
                    if required & ((row[0] is None) | (row[1] is None) << 1 | (row[2] is None) << 2):
                        self._raise_required_is_none(row, r)
            case 4:
                for r, row in enumerate(rows):
                    if required & ((row[0] is None) | (row[1] is None) << 1 | (row[2] is None) << 2 | (row[3] is None) << 3):
                        self._raise_required_is_none(row, r)
            case 5:
                for r, row in enumerate(rows):
                    if required & ((row[0] is None) | (row[1] is None) << 1 | (row[2] is None) << 2 | (row[3] is None) << 3 | (row[4] is None) << 4):
                        self._raise_required_is_none(row, r)
            case 6:
                for r, row in enumerate(rows):
                    if required & ((row[0] is None) | (row[1] is None) << 1 | (row[2] is None) << 2 | (row[3] is None) << 3 | (row[4] is None) << 4 | (row[5] is None) << 5):
                        self._raise_required_is_none(row, r)
            case 7:
                for r, row in enumerate(rows):
                    if required & ((row[0] is None) | (row[1] is None) << 1 | (row[2] is None) << 2 | (row[3] is None) << 3 | (row[4] is None) << 4 | (row[5] is None) << 5 | (row[6] is None) << 6):
                        self._raise_required_is_none(row, r)
            case 8:
                for r, row in enumerate(rows):
                    if required & ((row[0] is None) | (row[1] is None) << 1 | (row[2] is None) << 2 | (row[3] is None) << 3 | (row[4] is None) << 4 | (row[5] is None) << 5 | (row[6] is None) << 6 | (row[7] is None) << 7):
                        self._raise_required_is_none(row, r)
            case _:
                pass

    def check_row(self, row: tuple[Any, ...]) -> None:
        """
        Verifies if declared types match actual value types in a single row.
        """

        required = self.required
        if not required:
            return

        assert NUM_RESULTS <= 8

        match len(row):
            case 1:
                if required & (row[0] is None):
                    self._raise_required_is_none(row)
            case 2:
                if required & ((row[0] is None) | (row[1] is None) << 1):
                    self._raise_required_is_none(row)
            case 3:
                if required & ((row[0] is None) | (row[1] is None) << 1 | (row[2] is None) << 2):
                    self._raise_required_is_none(row)
            case 4:
                if required & ((row[0] is None) | (row[1] is None) << 1 | (row[2] is None) << 2 | (row[3] is None) << 3):
                    self._raise_required_is_none(row)
            case 5:
                if required & ((row[0] is None) | (row[1] is None) << 1 | (row[2] is None) << 2 | (row[3] is None) << 3 | (row[4] is None) << 4):
                    self._raise_required_is_none(row)
            case 6:
                if required & ((row[0] is None) | (row[1] is None) << 1 | (row[2] is None) << 2 | (row[3] is None) << 3 | (row[4] is None) << 4 | (row[5] is None) << 5):
                    self._raise_required_is_none(row)
            case 7:
                if required & ((row[0] is None) | (row[1] is None) << 1 | (row[2] is None) << 2 | (row[3] is None) << 3 | (row[4] is None) << 4 | (row[5] is None) << 5 | (row[6] is None) << 6):
                    self._raise_required_is_none(row)
            case 8:
                if required & ((row[0] is None) | (row[1] is None) << 1 | (row[2] is None) << 2 | (row[3] is None) << 3 | (row[4] is None) << 4 | (row[5] is None) << 5 | (row[6] is None) << 6 | (row[7] is None) << 7):
                    self._raise_required_is_none(row)
            case _:
                pass

    def check_value(self, value: Any) -> None:
        """
        Verifies if the declared type matches the actual value type.
        """

        if self.required and value is None:
            raise TypeError(f"expected: {self.resultset_data_types[0]}; got: NULL")

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

    SQLExpression: TypeAlias = Template | str

    class _SQLTemplate(_SQLObject):
        """
        A SQL query specified with the Python t-string syntax.
        """

        strings: tuple[str, ...]
        placeholders: tuple[_SQLPlaceholder, ...]

        def __init__(
            self,
            template: Template,
            *,
            args: type[Any] | None = None,
            resultset: type[Any] | None = None,
        ) -> None:
            super().__init__(args=args, resultset=resultset)

            for ip in template.interpolations:
                if ip.conversion is not None:
                    raise TypeError(f"interpolation `{ip.expression}` expected to apply no conversion")
                if ip.format_spec:
                    raise TypeError(f"interpolation `{ip.expression}` expected to apply no format spec")
                if not isinstance(ip.value, int):
                    raise TypeError(f"interpolation `{ip.expression}` expected to evaluate to an integer")

            self.strings = template.strings

            if args is not None:

                def _to_placeholder(ip: Interpolation) -> _SQLPlaceholder:
                    ordinal = int(ip.value)
                    if not (0 < ordinal <= len(self.parameter_data_types)):
                        raise IndexError(f"interpolation `{ip.expression}` is an ordinal out of range; expected: 0 < value <= {len(self.parameter_data_types)}")
                    return self.parameter_data_types[int(ip.value) - 1]

                self.placeholders = tuple(_to_placeholder(ip) for ip in template.interpolations)
            else:
                self.placeholders = ()

        def query(self) -> str:
            buf = StringIO()
            for s, p in zip(self.strings[:-1], self.placeholders, strict=True):
                buf.write(s)
                buf.write(f"${p.ordinal}")
            buf.write(self.strings[-1])
            return buf.getvalue()

else:
    SQLExpression = str


class _SQLString(_SQLObject):
    """
    A SQL query specified as a plain string (e.g. f-string).
    """

    sql: str

    def __init__(
        self,
        sql: str,
        *,
        args: type[Any] | None = None,
        resultset: type[Any] | None = None,
    ) -> None:
        super().__init__(args=args, resultset=resultset)
        self.sql = sql

    def query(self) -> str:
        return self.sql


class _SQL:
    """
    Represents a SQL statement with associated type information.
    """


Connection: TypeAlias = asyncpg.Connection | asyncpg.pool.PoolConnectionProxy


class _SQLImpl(_SQL):
    """
    Forwards input data to an `asyncpg.PreparedStatement`, and validates output data (if necessary).
    """

    sql: _SQLObject

    def __init__(self, sql: _SQLObject) -> None:
        self.sql = sql

    def __str__(self) -> str:
        return str(self.sql)

    def __repr__(self) -> str:
        return repr(self.sql)

    async def _prepare(self, connection: Connection) -> PreparedStatement:
        stmt = await connection.prepare(self.sql.query())

        for attr, data_type in zip(stmt.get_attributes(), self.sql.resultset_data_types, strict=True):
            if not check_data_type(attr.type.name, data_type):
                raise TypeError(f"expected: {data_type} in column `{attr.name}`; got: `{attr.type.kind}` of `{attr.type.name}`")

        return stmt

    async def execute(self, connection: asyncpg.Connection, *args: Any) -> None:
        await connection.execute(self.sql.query(), *args)

    async def executemany(self, connection: asyncpg.Connection, args: Iterable[Sequence[Any]]) -> None:
        stmt = await self._prepare(connection)
        await stmt.executemany(args)

    async def fetch(self, connection: asyncpg.Connection, *args: Any) -> list[tuple[Any, ...]]:
        stmt = await self._prepare(connection)
        rows = await stmt.fetch(*args)
        resultset = [tuple(value for value in row) for row in rows]
        self.sql.check_rows(resultset)
        return resultset

    async def fetchmany(self, connection: asyncpg.Connection, args: Iterable[Sequence[Any]]) -> list[tuple[Any, ...]]:
        stmt = await self._prepare(connection)
        rows = await stmt.fetchmany(args)  # type: ignore[arg-type, call-arg]  # pyright: ignore[reportCallIssue]
        rows = typing.cast(list[asyncpg.Record], rows)
        resultset = [tuple(value for value in row) for row in rows]
        self.sql.check_rows(resultset)
        return resultset

    async def fetchrow(self, connection: asyncpg.Connection, *args: Any) -> tuple[Any, ...] | None:
        stmt = await self._prepare(connection)
        row = await stmt.fetchrow(*args)
        if row is None:
            return None
        resultset = tuple(value for value in row)
        self.sql.check_row(resultset)
        return resultset

    async def fetchval(self, connection: asyncpg.Connection, *args: Any) -> Any:
        stmt = await self._prepare(connection)
        value = await stmt.fetchval(*args)
        self.sql.check_value(value)
        return value


### START OF AUTO-GENERATED BLOCK ###

P1 = TypeVar("P1")
P2 = TypeVar("P2")
P3 = TypeVar("P3")
P4 = TypeVar("P4")
P5 = TypeVar("P5")
P6 = TypeVar("P6")
P7 = TypeVar("P7")
P8 = TypeVar("P8")
R1 = TypeVar("R1")
R2 = TypeVar("R2")
R3 = TypeVar("R3")
R4 = TypeVar("R4")
R5 = TypeVar("R5")
R6 = TypeVar("R6")
R7 = TypeVar("R7")
R8 = TypeVar("R8")
PS = TypeVar("PS", bool, bool | None, int, int | None, float, float | None, Decimal, Decimal | None, date, date | None, time, time | None, datetime, datetime | None, str, str | None, bytes, bytes | None, UUID, UUID | None)
RS = TypeVar("RS", bool, bool | None, int, int | None, float, float | None, Decimal, Decimal | None, date, date | None, time, time | None, datetime, datetime | None, str, str | None, bytes, bytes | None, UUID, UUID | None)


class SQL_P0(_SQL):
    @abstractmethod
    async def execute(self, connection: Connection) -> None: ...


class SQL_P0_R1(Generic[R1], SQL_P0):
    @abstractmethod
    async def fetch(self, connection: Connection) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection) -> tuple[R1] | None: ...
    @abstractmethod
    async def fetchval(self, connection: Connection) -> R1: ...


class SQL_P0_R2(Generic[R1, R2], SQL_P0):
    @abstractmethod
    async def fetch(self, connection: Connection) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection) -> tuple[R1, R2] | None: ...


class SQL_P0_R3(Generic[R1, R2, R3], SQL_P0):
    @abstractmethod
    async def fetch(self, connection: Connection) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection) -> tuple[R1, R2, R3] | None: ...


class SQL_P0_R4(Generic[R1, R2, R3, R4], SQL_P0):
    @abstractmethod
    async def fetch(self, connection: Connection) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection) -> tuple[R1, R2, R3, R4] | None: ...


class SQL_P0_R5(Generic[R1, R2, R3, R4, R5], SQL_P0):
    @abstractmethod
    async def fetch(self, connection: Connection) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection) -> tuple[R1, R2, R3, R4, R5] | None: ...


class SQL_P0_R6(Generic[R1, R2, R3, R4, R5, R6], SQL_P0):
    @abstractmethod
    async def fetch(self, connection: Connection) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection) -> tuple[R1, R2, R3, R4, R5, R6] | None: ...


class SQL_P0_R7(Generic[R1, R2, R3, R4, R5, R6, R7], SQL_P0):
    @abstractmethod
    async def fetch(self, connection: Connection) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection) -> tuple[R1, R2, R3, R4, R5, R6, R7] | None: ...


class SQL_P0_R8(Generic[R1, R2, R3, R4, R5, R6, R7, R8], SQL_P0):
    @abstractmethod
    async def fetch(self, connection: Connection) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection) -> tuple[R1, R2, R3, R4, R5, R6, R7, R8] | None: ...


class SQL_P1(Generic[P1], _SQL):
    @abstractmethod
    async def execute(self, connection: Connection, arg1: P1) -> None: ...
    @abstractmethod
    async def executemany(self, connection: Connection, args: Iterable[tuple[P1]]) -> None: ...


class SQL_P1_R1(Generic[P1, R1], SQL_P1[P1]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1]]) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1) -> tuple[R1] | None: ...
    @abstractmethod
    async def fetchval(self, connection: Connection, arg1: P1) -> R1: ...


class SQL_P1_R2(Generic[P1, R1, R2], SQL_P1[P1]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1]]) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1) -> tuple[R1, R2] | None: ...


class SQL_P1_R3(Generic[P1, R1, R2, R3], SQL_P1[P1]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1]]) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1) -> tuple[R1, R2, R3] | None: ...


class SQL_P1_R4(Generic[P1, R1, R2, R3, R4], SQL_P1[P1]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1]]) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1) -> tuple[R1, R2, R3, R4] | None: ...


class SQL_P1_R5(Generic[P1, R1, R2, R3, R4, R5], SQL_P1[P1]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1]]) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1) -> tuple[R1, R2, R3, R4, R5] | None: ...


class SQL_P1_R6(Generic[P1, R1, R2, R3, R4, R5, R6], SQL_P1[P1]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1]]) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1) -> tuple[R1, R2, R3, R4, R5, R6] | None: ...


class SQL_P1_R7(Generic[P1, R1, R2, R3, R4, R5, R6, R7], SQL_P1[P1]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1) -> tuple[R1, R2, R3, R4, R5, R6, R7] | None: ...


class SQL_P1_R8(Generic[P1, R1, R2, R3, R4, R5, R6, R7, R8], SQL_P1[P1]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1) -> tuple[R1, R2, R3, R4, R5, R6, R7, R8] | None: ...


class SQL_P2(Generic[P1, P2], _SQL):
    @abstractmethod
    async def execute(self, connection: Connection, arg1: P1, arg2: P2) -> None: ...
    @abstractmethod
    async def executemany(self, connection: Connection, args: Iterable[tuple[P1, P2]]) -> None: ...


class SQL_P2_R1(Generic[P1, P2, R1], SQL_P2[P1, P2]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2]]) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2) -> tuple[R1] | None: ...
    @abstractmethod
    async def fetchval(self, connection: Connection, arg1: P1, arg2: P2) -> R1: ...


class SQL_P2_R2(Generic[P1, P2, R1, R2], SQL_P2[P1, P2]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2]]) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2) -> tuple[R1, R2] | None: ...


class SQL_P2_R3(Generic[P1, P2, R1, R2, R3], SQL_P2[P1, P2]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2]]) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2) -> tuple[R1, R2, R3] | None: ...


class SQL_P2_R4(Generic[P1, P2, R1, R2, R3, R4], SQL_P2[P1, P2]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2]]) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2) -> tuple[R1, R2, R3, R4] | None: ...


class SQL_P2_R5(Generic[P1, P2, R1, R2, R3, R4, R5], SQL_P2[P1, P2]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2]]) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2) -> tuple[R1, R2, R3, R4, R5] | None: ...


class SQL_P2_R6(Generic[P1, P2, R1, R2, R3, R4, R5, R6], SQL_P2[P1, P2]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2]]) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2) -> tuple[R1, R2, R3, R4, R5, R6] | None: ...


class SQL_P2_R7(Generic[P1, P2, R1, R2, R3, R4, R5, R6, R7], SQL_P2[P1, P2]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2) -> tuple[R1, R2, R3, R4, R5, R6, R7] | None: ...


class SQL_P2_R8(Generic[P1, P2, R1, R2, R3, R4, R5, R6, R7, R8], SQL_P2[P1, P2]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2) -> tuple[R1, R2, R3, R4, R5, R6, R7, R8] | None: ...


class SQL_P3(Generic[P1, P2, P3], _SQL):
    @abstractmethod
    async def execute(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> None: ...
    @abstractmethod
    async def executemany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3]]) -> None: ...


class SQL_P3_R1(Generic[P1, P2, P3, R1], SQL_P3[P1, P2, P3]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3]]) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> tuple[R1] | None: ...
    @abstractmethod
    async def fetchval(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> R1: ...


class SQL_P3_R2(Generic[P1, P2, P3, R1, R2], SQL_P3[P1, P2, P3]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3]]) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> tuple[R1, R2] | None: ...


class SQL_P3_R3(Generic[P1, P2, P3, R1, R2, R3], SQL_P3[P1, P2, P3]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3]]) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> tuple[R1, R2, R3] | None: ...


class SQL_P3_R4(Generic[P1, P2, P3, R1, R2, R3, R4], SQL_P3[P1, P2, P3]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3]]) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> tuple[R1, R2, R3, R4] | None: ...


class SQL_P3_R5(Generic[P1, P2, P3, R1, R2, R3, R4, R5], SQL_P3[P1, P2, P3]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3]]) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> tuple[R1, R2, R3, R4, R5] | None: ...


class SQL_P3_R6(Generic[P1, P2, P3, R1, R2, R3, R4, R5, R6], SQL_P3[P1, P2, P3]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3]]) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> tuple[R1, R2, R3, R4, R5, R6] | None: ...


class SQL_P3_R7(Generic[P1, P2, P3, R1, R2, R3, R4, R5, R6, R7], SQL_P3[P1, P2, P3]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> tuple[R1, R2, R3, R4, R5, R6, R7] | None: ...


class SQL_P3_R8(Generic[P1, P2, P3, R1, R2, R3, R4, R5, R6, R7, R8], SQL_P3[P1, P2, P3]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3) -> tuple[R1, R2, R3, R4, R5, R6, R7, R8] | None: ...


class SQL_P4(Generic[P1, P2, P3, P4], _SQL):
    @abstractmethod
    async def execute(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> None: ...
    @abstractmethod
    async def executemany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4]]) -> None: ...


class SQL_P4_R1(Generic[P1, P2, P3, P4, R1], SQL_P4[P1, P2, P3, P4]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4]]) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> tuple[R1] | None: ...
    @abstractmethod
    async def fetchval(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> R1: ...


class SQL_P4_R2(Generic[P1, P2, P3, P4, R1, R2], SQL_P4[P1, P2, P3, P4]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4]]) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> tuple[R1, R2] | None: ...


class SQL_P4_R3(Generic[P1, P2, P3, P4, R1, R2, R3], SQL_P4[P1, P2, P3, P4]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4]]) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> tuple[R1, R2, R3] | None: ...


class SQL_P4_R4(Generic[P1, P2, P3, P4, R1, R2, R3, R4], SQL_P4[P1, P2, P3, P4]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4]]) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> tuple[R1, R2, R3, R4] | None: ...


class SQL_P4_R5(Generic[P1, P2, P3, P4, R1, R2, R3, R4, R5], SQL_P4[P1, P2, P3, P4]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4]]) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> tuple[R1, R2, R3, R4, R5] | None: ...


class SQL_P4_R6(Generic[P1, P2, P3, P4, R1, R2, R3, R4, R5, R6], SQL_P4[P1, P2, P3, P4]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4]]) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> tuple[R1, R2, R3, R4, R5, R6] | None: ...


class SQL_P4_R7(Generic[P1, P2, P3, P4, R1, R2, R3, R4, R5, R6, R7], SQL_P4[P1, P2, P3, P4]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> tuple[R1, R2, R3, R4, R5, R6, R7] | None: ...


class SQL_P4_R8(Generic[P1, P2, P3, P4, R1, R2, R3, R4, R5, R6, R7, R8], SQL_P4[P1, P2, P3, P4]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4) -> tuple[R1, R2, R3, R4, R5, R6, R7, R8] | None: ...


class SQL_P5(Generic[P1, P2, P3, P4, P5], _SQL):
    @abstractmethod
    async def execute(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> None: ...
    @abstractmethod
    async def executemany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5]]) -> None: ...


class SQL_P5_R1(Generic[P1, P2, P3, P4, P5, R1], SQL_P5[P1, P2, P3, P4, P5]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5]]) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> tuple[R1] | None: ...
    @abstractmethod
    async def fetchval(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> R1: ...


class SQL_P5_R2(Generic[P1, P2, P3, P4, P5, R1, R2], SQL_P5[P1, P2, P3, P4, P5]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5]]) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> tuple[R1, R2] | None: ...


class SQL_P5_R3(Generic[P1, P2, P3, P4, P5, R1, R2, R3], SQL_P5[P1, P2, P3, P4, P5]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5]]) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> tuple[R1, R2, R3] | None: ...


class SQL_P5_R4(Generic[P1, P2, P3, P4, P5, R1, R2, R3, R4], SQL_P5[P1, P2, P3, P4, P5]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5]]) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> tuple[R1, R2, R3, R4] | None: ...


class SQL_P5_R5(Generic[P1, P2, P3, P4, P5, R1, R2, R3, R4, R5], SQL_P5[P1, P2, P3, P4, P5]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5]]) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> tuple[R1, R2, R3, R4, R5] | None: ...


class SQL_P5_R6(Generic[P1, P2, P3, P4, P5, R1, R2, R3, R4, R5, R6], SQL_P5[P1, P2, P3, P4, P5]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5]]) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> tuple[R1, R2, R3, R4, R5, R6] | None: ...


class SQL_P5_R7(Generic[P1, P2, P3, P4, P5, R1, R2, R3, R4, R5, R6, R7], SQL_P5[P1, P2, P3, P4, P5]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> tuple[R1, R2, R3, R4, R5, R6, R7] | None: ...


class SQL_P5_R8(Generic[P1, P2, P3, P4, P5, R1, R2, R3, R4, R5, R6, R7, R8], SQL_P5[P1, P2, P3, P4, P5]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5) -> tuple[R1, R2, R3, R4, R5, R6, R7, R8] | None: ...


class SQL_P6(Generic[P1, P2, P3, P4, P5, P6], _SQL):
    @abstractmethod
    async def execute(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> None: ...
    @abstractmethod
    async def executemany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6]]) -> None: ...


class SQL_P6_R1(Generic[P1, P2, P3, P4, P5, P6, R1], SQL_P6[P1, P2, P3, P4, P5, P6]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6]]) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> tuple[R1] | None: ...
    @abstractmethod
    async def fetchval(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> R1: ...


class SQL_P6_R2(Generic[P1, P2, P3, P4, P5, P6, R1, R2], SQL_P6[P1, P2, P3, P4, P5, P6]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6]]) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> tuple[R1, R2] | None: ...


class SQL_P6_R3(Generic[P1, P2, P3, P4, P5, P6, R1, R2, R3], SQL_P6[P1, P2, P3, P4, P5, P6]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6]]) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> tuple[R1, R2, R3] | None: ...


class SQL_P6_R4(Generic[P1, P2, P3, P4, P5, P6, R1, R2, R3, R4], SQL_P6[P1, P2, P3, P4, P5, P6]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6]]) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> tuple[R1, R2, R3, R4] | None: ...


class SQL_P6_R5(Generic[P1, P2, P3, P4, P5, P6, R1, R2, R3, R4, R5], SQL_P6[P1, P2, P3, P4, P5, P6]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6]]) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> tuple[R1, R2, R3, R4, R5] | None: ...


class SQL_P6_R6(Generic[P1, P2, P3, P4, P5, P6, R1, R2, R3, R4, R5, R6], SQL_P6[P1, P2, P3, P4, P5, P6]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6]]) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> tuple[R1, R2, R3, R4, R5, R6] | None: ...


class SQL_P6_R7(Generic[P1, P2, P3, P4, P5, P6, R1, R2, R3, R4, R5, R6, R7], SQL_P6[P1, P2, P3, P4, P5, P6]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> tuple[R1, R2, R3, R4, R5, R6, R7] | None: ...


class SQL_P6_R8(Generic[P1, P2, P3, P4, P5, P6, R1, R2, R3, R4, R5, R6, R7, R8], SQL_P6[P1, P2, P3, P4, P5, P6]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6) -> tuple[R1, R2, R3, R4, R5, R6, R7, R8] | None: ...


class SQL_P7(Generic[P1, P2, P3, P4, P5, P6, P7], _SQL):
    @abstractmethod
    async def execute(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> None: ...
    @abstractmethod
    async def executemany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7]]) -> None: ...


class SQL_P7_R1(Generic[P1, P2, P3, P4, P5, P6, P7, R1], SQL_P7[P1, P2, P3, P4, P5, P6, P7]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7]]) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> tuple[R1] | None: ...
    @abstractmethod
    async def fetchval(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> R1: ...


class SQL_P7_R2(Generic[P1, P2, P3, P4, P5, P6, P7, R1, R2], SQL_P7[P1, P2, P3, P4, P5, P6, P7]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7]]) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> tuple[R1, R2] | None: ...


class SQL_P7_R3(Generic[P1, P2, P3, P4, P5, P6, P7, R1, R2, R3], SQL_P7[P1, P2, P3, P4, P5, P6, P7]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7]]) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> tuple[R1, R2, R3] | None: ...


class SQL_P7_R4(Generic[P1, P2, P3, P4, P5, P6, P7, R1, R2, R3, R4], SQL_P7[P1, P2, P3, P4, P5, P6, P7]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7]]) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> tuple[R1, R2, R3, R4] | None: ...


class SQL_P7_R5(Generic[P1, P2, P3, P4, P5, P6, P7, R1, R2, R3, R4, R5], SQL_P7[P1, P2, P3, P4, P5, P6, P7]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7]]) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> tuple[R1, R2, R3, R4, R5] | None: ...


class SQL_P7_R6(Generic[P1, P2, P3, P4, P5, P6, P7, R1, R2, R3, R4, R5, R6], SQL_P7[P1, P2, P3, P4, P5, P6, P7]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7]]) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> tuple[R1, R2, R3, R4, R5, R6] | None: ...


class SQL_P7_R7(Generic[P1, P2, P3, P4, P5, P6, P7, R1, R2, R3, R4, R5, R6, R7], SQL_P7[P1, P2, P3, P4, P5, P6, P7]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> tuple[R1, R2, R3, R4, R5, R6, R7] | None: ...


class SQL_P7_R8(Generic[P1, P2, P3, P4, P5, P6, P7, R1, R2, R3, R4, R5, R6, R7, R8], SQL_P7[P1, P2, P3, P4, P5, P6, P7]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7) -> tuple[R1, R2, R3, R4, R5, R6, R7, R8] | None: ...


class SQL_P8(Generic[P1, P2, P3, P4, P5, P6, P7, P8], _SQL):
    @abstractmethod
    async def execute(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> None: ...
    @abstractmethod
    async def executemany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7, P8]]) -> None: ...


class SQL_P8_R1(Generic[P1, P2, P3, P4, P5, P6, P7, P8, R1], SQL_P8[P1, P2, P3, P4, P5, P6, P7, P8]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7, P8]]) -> list[tuple[R1]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> tuple[R1] | None: ...
    @abstractmethod
    async def fetchval(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> R1: ...


class SQL_P8_R2(Generic[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2], SQL_P8[P1, P2, P3, P4, P5, P6, P7, P8]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7, P8]]) -> list[tuple[R1, R2]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> tuple[R1, R2] | None: ...


class SQL_P8_R3(Generic[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2, R3], SQL_P8[P1, P2, P3, P4, P5, P6, P7, P8]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7, P8]]) -> list[tuple[R1, R2, R3]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> tuple[R1, R2, R3] | None: ...


class SQL_P8_R4(Generic[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2, R3, R4], SQL_P8[P1, P2, P3, P4, P5, P6, P7, P8]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7, P8]]) -> list[tuple[R1, R2, R3, R4]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> tuple[R1, R2, R3, R4] | None: ...


class SQL_P8_R5(Generic[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2, R3, R4, R5], SQL_P8[P1, P2, P3, P4, P5, P6, P7, P8]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7, P8]]) -> list[tuple[R1, R2, R3, R4, R5]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> tuple[R1, R2, R3, R4, R5] | None: ...


class SQL_P8_R6(Generic[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2, R3, R4, R5, R6], SQL_P8[P1, P2, P3, P4, P5, P6, P7, P8]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7, P8]]) -> list[tuple[R1, R2, R3, R4, R5, R6]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> tuple[R1, R2, R3, R4, R5, R6] | None: ...


class SQL_P8_R7(Generic[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2, R3, R4, R5, R6, R7], SQL_P8[P1, P2, P3, P4, P5, P6, P7, P8]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7, P8]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> tuple[R1, R2, R3, R4, R5, R6, R7] | None: ...


class SQL_P8_R8(Generic[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2, R3, R4, R5, R6, R7, R8], SQL_P8[P1, P2, P3, P4, P5, P6, P7, P8]):
    @abstractmethod
    async def fetch(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchmany(self, connection: Connection, args: Iterable[tuple[P1, P2, P3, P4, P5, P6, P7, P8]]) -> list[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]: ...
    @abstractmethod
    async def fetchrow(self, connection: Connection, arg1: P1, arg2: P2, arg3: P3, arg4: P4, arg5: P5, arg6: P6, arg7: P7, arg8: P8) -> tuple[R1, R2, R3, R4, R5, R6, R7, R8] | None: ...


@overload
def sql(stmt: SQLExpression) -> SQL_P0: ...
@overload
def sql(stmt: SQLExpression, *, resultset: type[RS]) -> SQL_P0_R1[RS]: ...
@overload
def sql(stmt: SQLExpression, *, resultset: type[tuple[R1]]) -> SQL_P0_R1[R1]: ...
@overload
def sql(stmt: SQLExpression, *, resultset: type[tuple[R1, R2]]) -> SQL_P0_R2[R1, R2]: ...
@overload
def sql(stmt: SQLExpression, *, resultset: type[tuple[R1, R2, R3]]) -> SQL_P0_R3[R1, R2, R3]: ...
@overload
def sql(stmt: SQLExpression, *, resultset: type[tuple[R1, R2, R3, R4]]) -> SQL_P0_R4[R1, R2, R3, R4]: ...
@overload
def sql(stmt: SQLExpression, *, resultset: type[tuple[R1, R2, R3, R4, R5]]) -> SQL_P0_R5[R1, R2, R3, R4, R5]: ...
@overload
def sql(stmt: SQLExpression, *, resultset: type[tuple[R1, R2, R3, R4, R5, R6]]) -> SQL_P0_R6[R1, R2, R3, R4, R5, R6]: ...
@overload
def sql(stmt: SQLExpression, *, resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7]]) -> SQL_P0_R7[R1, R2, R3, R4, R5, R6, R7]: ...
@overload
def sql(stmt: SQLExpression, *, resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]) -> SQL_P0_R8[R1, R2, R3, R4, R5, R6, R7, R8]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[PS]) -> SQL_P1[PS]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1]]) -> SQL_P1[P1]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[PS], resultset: type[RS]) -> SQL_P1_R1[PS, RS]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1]], resultset: type[tuple[R1]]) -> SQL_P1_R1[P1, R1]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[PS], resultset: type[tuple[R1, R2]]) -> SQL_P1_R2[PS, R1, R2]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1]], resultset: type[tuple[R1, R2]]) -> SQL_P1_R2[P1, R1, R2]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[PS], resultset: type[tuple[R1, R2, R3]]) -> SQL_P1_R3[PS, R1, R2, R3]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1]], resultset: type[tuple[R1, R2, R3]]) -> SQL_P1_R3[P1, R1, R2, R3]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[PS], resultset: type[tuple[R1, R2, R3, R4]]) -> SQL_P1_R4[PS, R1, R2, R3, R4]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1]], resultset: type[tuple[R1, R2, R3, R4]]) -> SQL_P1_R4[P1, R1, R2, R3, R4]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[PS], resultset: type[tuple[R1, R2, R3, R4, R5]]) -> SQL_P1_R5[PS, R1, R2, R3, R4, R5]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1]], resultset: type[tuple[R1, R2, R3, R4, R5]]) -> SQL_P1_R5[P1, R1, R2, R3, R4, R5]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[PS], resultset: type[tuple[R1, R2, R3, R4, R5, R6]]) -> SQL_P1_R6[PS, R1, R2, R3, R4, R5, R6]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1]], resultset: type[tuple[R1, R2, R3, R4, R5, R6]]) -> SQL_P1_R6[P1, R1, R2, R3, R4, R5, R6]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[PS], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7]]) -> SQL_P1_R7[PS, R1, R2, R3, R4, R5, R6, R7]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7]]) -> SQL_P1_R7[P1, R1, R2, R3, R4, R5, R6, R7]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[PS], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]) -> SQL_P1_R8[PS, R1, R2, R3, R4, R5, R6, R7, R8]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]) -> SQL_P1_R8[P1, R1, R2, R3, R4, R5, R6, R7, R8]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2]]) -> SQL_P2[P1, P2]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2]], resultset: type[RS]) -> SQL_P2_R1[P1, P2, RS]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2]], resultset: type[tuple[R1]]) -> SQL_P2_R1[P1, P2, R1]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2]], resultset: type[tuple[R1, R2]]) -> SQL_P2_R2[P1, P2, R1, R2]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2]], resultset: type[tuple[R1, R2, R3]]) -> SQL_P2_R3[P1, P2, R1, R2, R3]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2]], resultset: type[tuple[R1, R2, R3, R4]]) -> SQL_P2_R4[P1, P2, R1, R2, R3, R4]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2]], resultset: type[tuple[R1, R2, R3, R4, R5]]) -> SQL_P2_R5[P1, P2, R1, R2, R3, R4, R5]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2]], resultset: type[tuple[R1, R2, R3, R4, R5, R6]]) -> SQL_P2_R6[P1, P2, R1, R2, R3, R4, R5, R6]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7]]) -> SQL_P2_R7[P1, P2, R1, R2, R3, R4, R5, R6, R7]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]) -> SQL_P2_R8[P1, P2, R1, R2, R3, R4, R5, R6, R7, R8]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3]]) -> SQL_P3[P1, P2, P3]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3]], resultset: type[RS]) -> SQL_P3_R1[P1, P2, P3, RS]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3]], resultset: type[tuple[R1]]) -> SQL_P3_R1[P1, P2, P3, R1]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3]], resultset: type[tuple[R1, R2]]) -> SQL_P3_R2[P1, P2, P3, R1, R2]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3]], resultset: type[tuple[R1, R2, R3]]) -> SQL_P3_R3[P1, P2, P3, R1, R2, R3]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3]], resultset: type[tuple[R1, R2, R3, R4]]) -> SQL_P3_R4[P1, P2, P3, R1, R2, R3, R4]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3]], resultset: type[tuple[R1, R2, R3, R4, R5]]) -> SQL_P3_R5[P1, P2, P3, R1, R2, R3, R4, R5]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3]], resultset: type[tuple[R1, R2, R3, R4, R5, R6]]) -> SQL_P3_R6[P1, P2, P3, R1, R2, R3, R4, R5, R6]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7]]) -> SQL_P3_R7[P1, P2, P3, R1, R2, R3, R4, R5, R6, R7]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]) -> SQL_P3_R8[P1, P2, P3, R1, R2, R3, R4, R5, R6, R7, R8]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4]]) -> SQL_P4[P1, P2, P3, P4]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4]], resultset: type[RS]) -> SQL_P4_R1[P1, P2, P3, P4, RS]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4]], resultset: type[tuple[R1]]) -> SQL_P4_R1[P1, P2, P3, P4, R1]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4]], resultset: type[tuple[R1, R2]]) -> SQL_P4_R2[P1, P2, P3, P4, R1, R2]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4]], resultset: type[tuple[R1, R2, R3]]) -> SQL_P4_R3[P1, P2, P3, P4, R1, R2, R3]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4]], resultset: type[tuple[R1, R2, R3, R4]]) -> SQL_P4_R4[P1, P2, P3, P4, R1, R2, R3, R4]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4]], resultset: type[tuple[R1, R2, R3, R4, R5]]) -> SQL_P4_R5[P1, P2, P3, P4, R1, R2, R3, R4, R5]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4]], resultset: type[tuple[R1, R2, R3, R4, R5, R6]]) -> SQL_P4_R6[P1, P2, P3, P4, R1, R2, R3, R4, R5, R6]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7]]) -> SQL_P4_R7[P1, P2, P3, P4, R1, R2, R3, R4, R5, R6, R7]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]) -> SQL_P4_R8[P1, P2, P3, P4, R1, R2, R3, R4, R5, R6, R7, R8]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5]]) -> SQL_P5[P1, P2, P3, P4, P5]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5]], resultset: type[RS]) -> SQL_P5_R1[P1, P2, P3, P4, P5, RS]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5]], resultset: type[tuple[R1]]) -> SQL_P5_R1[P1, P2, P3, P4, P5, R1]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5]], resultset: type[tuple[R1, R2]]) -> SQL_P5_R2[P1, P2, P3, P4, P5, R1, R2]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5]], resultset: type[tuple[R1, R2, R3]]) -> SQL_P5_R3[P1, P2, P3, P4, P5, R1, R2, R3]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5]], resultset: type[tuple[R1, R2, R3, R4]]) -> SQL_P5_R4[P1, P2, P3, P4, P5, R1, R2, R3, R4]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5]], resultset: type[tuple[R1, R2, R3, R4, R5]]) -> SQL_P5_R5[P1, P2, P3, P4, P5, R1, R2, R3, R4, R5]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5]], resultset: type[tuple[R1, R2, R3, R4, R5, R6]]) -> SQL_P5_R6[P1, P2, P3, P4, P5, R1, R2, R3, R4, R5, R6]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7]]) -> SQL_P5_R7[P1, P2, P3, P4, P5, R1, R2, R3, R4, R5, R6, R7]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]) -> SQL_P5_R8[P1, P2, P3, P4, P5, R1, R2, R3, R4, R5, R6, R7, R8]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6]]) -> SQL_P6[P1, P2, P3, P4, P5, P6]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6]], resultset: type[RS]) -> SQL_P6_R1[P1, P2, P3, P4, P5, P6, RS]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6]], resultset: type[tuple[R1]]) -> SQL_P6_R1[P1, P2, P3, P4, P5, P6, R1]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6]], resultset: type[tuple[R1, R2]]) -> SQL_P6_R2[P1, P2, P3, P4, P5, P6, R1, R2]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6]], resultset: type[tuple[R1, R2, R3]]) -> SQL_P6_R3[P1, P2, P3, P4, P5, P6, R1, R2, R3]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6]], resultset: type[tuple[R1, R2, R3, R4]]) -> SQL_P6_R4[P1, P2, P3, P4, P5, P6, R1, R2, R3, R4]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6]], resultset: type[tuple[R1, R2, R3, R4, R5]]) -> SQL_P6_R5[P1, P2, P3, P4, P5, P6, R1, R2, R3, R4, R5]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6]], resultset: type[tuple[R1, R2, R3, R4, R5, R6]]) -> SQL_P6_R6[P1, P2, P3, P4, P5, P6, R1, R2, R3, R4, R5, R6]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7]]) -> SQL_P6_R7[P1, P2, P3, P4, P5, P6, R1, R2, R3, R4, R5, R6, R7]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]) -> SQL_P6_R8[P1, P2, P3, P4, P5, P6, R1, R2, R3, R4, R5, R6, R7, R8]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7]]) -> SQL_P7[P1, P2, P3, P4, P5, P6, P7]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7]], resultset: type[RS]) -> SQL_P7_R1[P1, P2, P3, P4, P5, P6, P7, RS]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7]], resultset: type[tuple[R1]]) -> SQL_P7_R1[P1, P2, P3, P4, P5, P6, P7, R1]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7]], resultset: type[tuple[R1, R2]]) -> SQL_P7_R2[P1, P2, P3, P4, P5, P6, P7, R1, R2]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7]], resultset: type[tuple[R1, R2, R3]]) -> SQL_P7_R3[P1, P2, P3, P4, P5, P6, P7, R1, R2, R3]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7]], resultset: type[tuple[R1, R2, R3, R4]]) -> SQL_P7_R4[P1, P2, P3, P4, P5, P6, P7, R1, R2, R3, R4]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7]], resultset: type[tuple[R1, R2, R3, R4, R5]]) -> SQL_P7_R5[P1, P2, P3, P4, P5, P6, P7, R1, R2, R3, R4, R5]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7]], resultset: type[tuple[R1, R2, R3, R4, R5, R6]]) -> SQL_P7_R6[P1, P2, P3, P4, P5, P6, P7, R1, R2, R3, R4, R5, R6]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7]]) -> SQL_P7_R7[P1, P2, P3, P4, P5, P6, P7, R1, R2, R3, R4, R5, R6, R7]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]) -> SQL_P7_R8[P1, P2, P3, P4, P5, P6, P7, R1, R2, R3, R4, R5, R6, R7, R8]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7, P8]]) -> SQL_P8[P1, P2, P3, P4, P5, P6, P7, P8]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7, P8]], resultset: type[RS]) -> SQL_P8_R1[P1, P2, P3, P4, P5, P6, P7, P8, RS]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7, P8]], resultset: type[tuple[R1]]) -> SQL_P8_R1[P1, P2, P3, P4, P5, P6, P7, P8, R1]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7, P8]], resultset: type[tuple[R1, R2]]) -> SQL_P8_R2[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7, P8]], resultset: type[tuple[R1, R2, R3]]) -> SQL_P8_R3[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2, R3]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7, P8]], resultset: type[tuple[R1, R2, R3, R4]]) -> SQL_P8_R4[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2, R3, R4]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7, P8]], resultset: type[tuple[R1, R2, R3, R4, R5]]) -> SQL_P8_R5[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2, R3, R4, R5]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7, P8]], resultset: type[tuple[R1, R2, R3, R4, R5, R6]]) -> SQL_P8_R6[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2, R3, R4, R5, R6]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7, P8]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7]]) -> SQL_P8_R7[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2, R3, R4, R5, R6, R7]: ...
@overload
def sql(stmt: SQLExpression, *, args: type[tuple[P1, P2, P3, P4, P5, P6, P7, P8]], resultset: type[tuple[R1, R2, R3, R4, R5, R6, R7, R8]]) -> SQL_P8_R8[P1, P2, P3, P4, P5, P6, P7, P8, R1, R2, R3, R4, R5, R6, R7, R8]: ...


### END OF AUTO-GENERATED BLOCK ###


def sql(
    stmt: SQLExpression,
    *,
    args: type[Any] | None = None,
    resultset: type[Any] | None = None,
) -> _SQL:
    """
    Creates a SQL statement with associated type information.

    :param stmt: SQL statement as a string or template.
    :param args: Type signature for input parameters. Use the type for a single parameter (e.g. `int`) or `tuple[...]` for multiple parameters.
    :param resultset: Type signature for output data. Use the type for a single parameter (e.g. `int`) or `tuple[...]` for multiple parameters.
    """

    if sys.version_info >= (3, 14):
        obj: _SQLObject
        match stmt:
            case Template():
                obj = _SQLTemplate(stmt, args=args, resultset=resultset)
            case str():
                obj = _SQLString(stmt, args=args, resultset=resultset)
    else:
        obj = _SQLString(stmt, args=args, resultset=resultset)

    return _SQLImpl(obj)
