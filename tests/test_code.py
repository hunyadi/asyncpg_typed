"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

import random
import re
import unittest
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID


def _class(p: int, r: int) -> str:
    """
    Emits a class name based on argument and resultset types.

    * Inbound types start with `P`.
    * Outbound types start with `R`.
    * Suffix `0` denotes no parameters of that type.
    * Suffix `1` denotes a singular type.
    * Suffix `X` denotes any number of items (starting at 0).

    :param p: Number of inbound parameters.
    :param r: Number of outbound parameters.
    """

    pm = {0: "0", 1: "X", 2: "X"}
    if r > 0:
        rm = {1: "1", 2: "X"}
        return f"SQL_R{rm[r]}_P{pm[p]}"
    else:
        return f"SQL_P{pm[p]}"


def _arg_list(p: int, r: int, s: bool) -> str:
    args: list[str] = []

    if p == 1:
        args.append("arg: type[P1]")
    elif p > 1:
        args.append("args: type[tuple[P1, Unpack[PX]]]")

    if r == 1:
        if s:
            args.append("result: type[R1]")
        else:
            args.append("resultset: type[tuple[R1]]")
    elif r > 1:
        args.append("resultset: type[tuple[R1, R2, Unpack[RX]]]")

    if args:
        return f", *, {', '.join(args)}"
    else:
        return ""


def _param_list(p: int, r: int) -> str:
    params: list[str] = []
    if r == 1:
        params.append("R1")
    elif r > 1:
        params.append("tuple[R1, R2, Unpack[RX]]")

    if p == 1:
        params.append("P1")
    elif p > 1:
        params.append("P1, Unpack[PX]")

    if params:
        return f"[{', '.join(params)}]"
    else:
        return ""


def _write_classes(out: TextIO) -> None:
    "Generates code for `Protocol` classes to match argument/resultset signature combinations with permitted operations."

    for p in range(2):
        if p > 0:
            print(f"class {_class(p, 0)}(Protocol[Unpack[PX]]):", file=out)

            print("    @abstractmethod", file=out)
            print("    async def execute(self, connection: Connection, *args: Unpack[PX]) -> None: ...", file=out)
            print("    @abstractmethod", file=out)
            print("    async def executemany(self, connection: Connection, args: Iterable[tuple[Unpack[PX]]]) -> None: ...", file=out)
        else:
            print("class SQL_P0(Protocol):", file=out)
            print("    @abstractmethod", file=out)
            print("    async def execute(self, connection: Connection) -> None: ...", file=out)

        for r in range(1, 3):
            if r == 1:
                resultset_param = "R1"
                resultset_return = "tuple[R1]"
            else:
                resultset_param = "RT"
                resultset_return = "RT"

            if p > 0:
                bases = f"{_class(p, 0)}[Unpack[PX]], Protocol[{resultset_param}, Unpack[PX]]"
            else:
                bases = f"SQL_P0, Protocol[{resultset_param}]"

            print(f"class {_class(p, r)}({bases}):", file=out)

            if p > 0:
                pos_args = ", *args: Unpack[PX]"
            else:
                pos_args = ""

            print(r"    @abstractmethod", file=out)
            print(f"    async def fetch(self, connection: Connection{pos_args}) -> list[{resultset_return}]: ...", file=out)

            if p > 0:
                print(r"    @abstractmethod", file=out)
                print(f"    async def fetchmany(self, connection: Connection, args: Iterable[tuple[Unpack[PX]]]) -> list[{resultset_return}]: ...", file=out)

            print(r"    @abstractmethod", file=out)
            print(f"    async def fetchrow(self, connection: Connection{pos_args}) -> {resultset_return} | None: ...", file=out)

            if r == 1:
                print(r"    @abstractmethod", file=out)
                print(f"    async def fetchval(self, connection: Connection{pos_args}) -> R1: ...", file=out)


def _write_function(out: TextIO, name: str, stmt: str, p: int, r: int, s: bool) -> None:
    """
    Writes an overload function for creating a typed SQL query.

    :param name: Function name.
    :param stmt: SQL statement type.
    :param p: Number of inbound parameters.
    :param r: Number of outbound parameters.
    :param s: Whether to use singular types.
    """

    print(r"@overload", file=out)
    print(f"def {name}(stmt: {stmt}{_arg_list(p, r, s)}) -> {_class(p, r)}{_param_list(p, r)}: ...", file=out)


def _write_sql(out: TextIO) -> None:
    "Generates code for the function `sql` to accept various argument/resultset signature combinations."

    for p in range(3):
        for r in range(3):
            if r == 1:
                _write_function(out, "sql", "SQLExpression", p, r, True)
            _write_function(out, "sql", "SQLExpression", p, r, False)


def _write_unsafe_sql(out: TextIO) -> None:
    "Generates code for the function `unsafe_sql` to accept various argument/resultset signature combinations."

    for p in range(3):
        for r in range(3):
            if r == 1:
                _write_function(out, "unsafe_sql", "str", p, r, True)
            _write_function(out, "unsafe_sql", "str", p, r, False)


def _instantiate(tp: type[Any]) -> str:
    "Writes code to instantiate an object of the given type."

    if tp is datetime:
        return "datetime.now()"
    elif tp is date:
        return f"date({random.randint(1900, 2100)}, {random.randint(1, 12)}, {random.randint(1, 28)})"
    else:
        return f"{tp.__name__}()"


def _random_type() -> type[Any]:
    return random.choice([bool, int, float, Decimal, date, time, datetime, timedelta, str, bytes, UUID])


def _update_code(source_code: str, block_name: str, writer: Callable[[TextIO], None]) -> str:
    prolog = f"### START OF AUTO-GENERATED BLOCK FOR {block_name} ###\n"
    epilog = f"### END OF AUTO-GENERATED BLOCK FOR {block_name} ###\n"

    stream = StringIO()
    writer(stream)
    code = stream.getvalue()

    search = "\n".join([prolog, r".*?", epilog])
    repl = "\n".join([prolog, code, epilog])
    source_code, count = re.subn(search, repl, source_code, count=1, flags=re.DOTALL)
    if count != 1:
        raise ValueError(f"expected: a single match; got: {count}")
    return source_code


class TestCode(unittest.TestCase):
    def test_update(self) -> None:
        source_file = Path(__file__).parent.parent / "asyncpg_typed" / "__init__.py"
        source_code = source_file.read_text(encoding="utf-8")

        source_code = _update_code(source_code, "Protocol", _write_classes)
        source_code = _update_code(source_code, "sql", _write_sql)
        source_code = _update_code(source_code, "unsafe_sql", _write_unsafe_sql)

        source_file.write_text(source_code, encoding="utf-8")

    def test_verify(self) -> None:
        with open(Path(__file__).parent / "sample.py", "w") as f:
            print("from datetime import date, datetime, time, timedelta", file=f)
            print("from decimal import Decimal", file=f)
            print("from typing import assert_type", file=f)
            print("from uuid import UUID", file=f)
            print(file=f)
            print("from asyncpg_typed import sql", file=f)
            print("from tests.connection import get_connection", file=f)
            print(file=f)
            print(file=f)

            print("async def main() -> None:", file=f)
            print("    async with get_connection() as conn:", file=f)

            for p in range(10):
                for r in range(10):
                    kwargs: list[str] = []

                    if p == 1:
                        input_type_list = [_random_type()]
                        kwargs.append(f"arg={input_type_list[0].__name__}")
                    elif p > 0:
                        input_type_list = [_random_type() for _ in range(p)]
                        kwargs.append(f"args=tuple[{', '.join(tp.__name__ for tp in input_type_list)}]")
                    else:
                        input_type_list = []

                    if r == 1:
                        output_type_list = [_random_type()]
                        kwargs.append(f"result={output_type_list[0].__name__}")
                    elif r > 0:
                        output_type_list = [_random_type() for _ in range(r)]
                        kwargs.append(f"resultset=tuple[{', '.join(tp.__name__ for tp in output_type_list)}]")
                    else:
                        output_type_list = []

                    if not kwargs:
                        continue

                    var = f"sql_{p}_{r}"
                    print(f'        {var} = sql("test", {", ".join(kwargs)})', file=f)

                    if input_type_list:
                        arg_items = ", ".join(_instantiate(tp) for tp in input_type_list)
                        args = ", " + arg_items

                        print(f"        await {var}.execute(conn{args})", file=f)
                        if len(input_type_list) == 1:
                            args_tuple = f"({arg_items}, )"
                        else:
                            args_tuple = f"({arg_items})"
                        print(f"        await {var}.executemany(conn, [{args_tuple}])", file=f)
                    else:
                        args = ""

                    if output_type_list:
                        output_types = ", ".join(tp.__name__ for tp in output_type_list)
                        print(f"        assert_type(await {var}.fetch(conn{args}), list[tuple[{output_types}]])", file=f)
                        print(f"        assert_type(await {var}.fetchrow(conn{args}), tuple[{output_types}] | None)", file=f)

                        if len(output_type_list) == 1:
                            print(f"        assert_type(await {var}.fetchval(conn{args}), {output_type_list[0].__name__})", file=f)

                    print(file=f)


if __name__ == "__main__":
    unittest.main()
