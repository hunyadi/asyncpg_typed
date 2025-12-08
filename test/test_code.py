"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

import re
import unittest
from io import StringIO
from pathlib import Path
from typing import TextIO

from asyncpg_typed import DATA_TYPES, NUM_ARGS


def _args_and_results(p: int, r: int, s: bool = False) -> str:
    """
    Emits a generic parameter list for both argument and resultset types.

    * Inbound types start with `P`.
    * Outbound types start with `R`.
    * Suffix `S` denotes a singular type.
    * Suffix `X` denotes any number of items (starting at 0).
    * Numbers indicate position in a tuple type (starting at 1).

    :param p: Number of inbound parameters.
    :param r: Number of outbound parameters.
    :param s: Whether to use singular types.
    """

    items: list[str] = []
    if s and p == 1:
        items.append("PS")
    else:
        items.extend(f"P{k + 1}" for k in range(p))
    if s and r == 1:
        items.append("RS")
    else:
        if r > 0:
            items.append("R1")
        if r > 1:
            items.append("R2")
            items.append("Unpack[RX]")
    if items:
        return f"[{', '.join(items)}]"
    else:
        return ""


def _args(p: int, s: bool = False) -> str:
    """
    Emits a generic parameter list for argument types.
    """

    return _args_and_results(p, 0, s)


def _results(r: int, s: bool = False) -> str:
    """
    Emits a generic parameter list for resultset types.
    """

    return _args_and_results(0, r, s)


def _params(p: int) -> str:
    """
    Emits a formal parameter list of numbered `arg` (starting at 1).
    """

    if p > 0:
        return ", " + ", ".join(f"arg{k + 1}: P{k + 1}" for k in range(p))
    else:
        return ""


def _param_spec(p: int, r: int, s: bool = False) -> str:
    """
    Emits formal parameters for the inbound (`args`) and outbound (`resultset`) parameter type specification.
    """

    params: list[str] = ["*"]
    if (s and p > 1) or (not s and p > 0):
        params.append(f"args: type[tuple{_args(p)}]")
    elif s and p == 1:
        params.append("args: type[PS]")
    if (s and r > 1) or (not s and r > 0):
        params.append(f"resultset: type[tuple{_results(r)}]")
    elif s and r == 1:
        params.append("resultset: type[RS]")
    if len(params) > 1:
        return f", {', '.join(params)}" if params else ""
    else:
        return ""


def _class(p: int, r: int) -> str:
    if r > 1:
        return f"SQL_P{p}_RX"
    elif r == 1:
        return f"SQL_P{p}_RS"
    else:
        return f"SQL_P{p}"


def _write_function(out: TextIO, p: int, r: int, s: bool) -> None:
    print(r"@overload", file=out)
    print(f"def sql(stmt: SQLExpression{_param_spec(p, r, s)}) -> {_class(p, r)}{_args_and_results(p, r, s)}: ...", file=out)


def write_code(out: TextIO) -> None:
    data_types_list = ", ".join(f"{data_type.__name__}, {data_type.__name__} | None" for data_type in DATA_TYPES)
    print(f'PS = TypeVar("PS", {data_types_list})', file=out)

    for p in range(1, NUM_ARGS + 1):
        print(f'P{p} = TypeVar("P{p}")', file=out)

    print(f'RS = TypeVar("RS", {data_types_list})', file=out)
    print('R1 = TypeVar("R1")', file=out)
    print('R2 = TypeVar("R2")', file=out)
    print('RX = TypeVarTuple("RX")', file=out)

    for p in range(NUM_ARGS + 1):
        if p > 0:
            print(f"class {_class(p, 0)}(Generic{_args(p)}, _SQL):", file=out)

            print(r"    @abstractmethod", file=out)
            print(f"    async def execute(self, connection: Connection{_params(p)}) -> None: ...", file=out)
            print(r"    @abstractmethod", file=out)
            print(f"    async def executemany(self, connection: Connection, args: Iterable[tuple{_args(p)}]) -> None: ...", file=out)
        else:
            print(f"class SQL_P{p}(_SQL):", file=out)
            print(r"    @abstractmethod", file=out)
            print(r"    async def execute(self, connection: Connection) -> None: ...", file=out)

        for r in range(1, 3):
            print(f"class {_class(p, r)}(Generic{_args_and_results(p, r)}, {_class(p, 0)}{_args(p)}):", file=out)

            print(r"    @abstractmethod", file=out)
            print(f"    async def fetch(self, connection: Connection{_params(p)}) -> list[tuple{_results(r)}]: ...", file=out)

            if p > 0:
                print(r"    @abstractmethod", file=out)
                print(f"    async def fetchmany(self, connection: Connection, args: Iterable[tuple{_args(p)}]) -> list[tuple{_results(r)}]: ...", file=out)

            print(r"    @abstractmethod", file=out)
            print(f"    async def fetchrow(self, connection: Connection{_params(p)}) -> tuple{_results(r)} | None: ...", file=out)

            if r == 1:
                print(r"    @abstractmethod", file=out)
                print(f"    async def fetchval(self, connection: Connection{_params(p)}) -> R{r}: ...", file=out)

    for p in range(NUM_ARGS + 1):
        for r in range(3):
            if p == 1 or r == 1:
                _write_function(out, p, r, True)
            _write_function(out, p, r, False)


def generate_code() -> str:
    stream = StringIO()
    write_code(stream)
    return stream.getvalue()


class TestCode(unittest.TestCase):
    def test_code(self) -> None:
        self.assertTrue(generate_code())

    def test_update(self) -> None:
        source_file = Path(__file__).parent.parent / "asyncpg_typed" / "__init__.py"
        source_code = source_file.read_text(encoding="utf-8")

        prolog = "### START OF AUTO-GENERATED BLOCK ###\n"
        epilog = "### END OF AUTO-GENERATED BLOCK ###\n"
        code = generate_code()

        search = "\n".join([prolog, r".*?", epilog])
        repl = "\n".join([prolog, code, epilog])
        source_code, count = re.subn(search, repl, source_code, count=1, flags=re.DOTALL)
        self.assertEqual(count, 1)

        source_file.write_text(source_code, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
