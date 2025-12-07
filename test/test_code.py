"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

import re
import unittest
from io import StringIO
from pathlib import Path
from typing import TextIO

from asyncpg_typed import DATA_TYPES, NUM_ARGS, NUM_RESULTS


def _args_and_results(p: int, r: int, s: bool = False) -> str:
    """
    Emits a generic parameter list for both argument and resultset types.

    * Inbound types start with `P`.
    * Outbound types start with `R`.
    * `S` denotes a singular type.
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
        items.extend(f"R{k + 1}" for k in range(r))
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


def _type_spec(p: int, r: int, s: bool = False) -> str:
    return _args_and_results(p, r, s)


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


def _write_function(out: TextIO, p: int, r: int, s: bool, *, use_modern_generic_syntax: bool = False) -> None:
    if r > 0:
        class_type = f"SQL_P{p}_R{r}"
    else:
        class_type = f"SQL_P{p}"

    print(r"@overload", file=out)
    if use_modern_generic_syntax:
        print(f"def sql{_type_spec(p, r, s)}(stmt: SQLExpression{_param_spec(p, r, s)}) -> {class_type}{_args_and_results(p, r, s)}: ...", file=out)
    else:
        print(f"def sql(stmt: SQLExpression{_param_spec(p, r, s)}) -> {class_type}{_args_and_results(p, r, s)}: ...", file=out)


def write_code(out: TextIO, *, use_modern_generic_syntax: bool = False) -> None:
    if not use_modern_generic_syntax:
        for p in range(1, NUM_ARGS + 1):
            print(f'P{p} = TypeVar("P{p}")', file=out)

        for r in range(1, NUM_RESULTS + 1):
            print(f'R{r} = TypeVar("R{r}")', file=out)

        data_types_list = ", ".join(f"{data_type.__name__}, {data_type.__name__} | None" for data_type in DATA_TYPES)
        print(f'PS = TypeVar("PS", {data_types_list})', file=out)
        print(f'RS = TypeVar("RS", {data_types_list})', file=out)

    for p in range(NUM_ARGS + 1):
        if p > 0:
            if use_modern_generic_syntax:
                print(f"class SQL_P{p}{_args(p)}(_SQL):", file=out)
            else:
                print(f"class SQL_P{p}(Generic{_args(p)}, _SQL):", file=out)

            print(r"    @abstractmethod", file=out)
            print(f"    async def execute(self, connection: Connection{_params(p)}) -> None: ...", file=out)
            print(r"    @abstractmethod", file=out)
            print(f"    async def executemany(self, connection: Connection, args: Iterable[tuple{_args(p)}]) -> None: ...", file=out)
        else:
            print(f"class SQL_P{p}(_SQL):", file=out)
            print(r"    @abstractmethod", file=out)
            print(r"    async def execute(self, connection: Connection) -> None: ...", file=out)

        for r in range(1, NUM_RESULTS + 1):
            if use_modern_generic_syntax:
                print(f"class SQL_P{p}_R{r}{_args_and_results(p, r)}(SQL_P{p}{_args(p)}):", file=out)
            else:
                print(f"class SQL_P{p}_R{r}(Generic{_args_and_results(p, r)}, SQL_P{p}{_args(p)}):", file=out)

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
        for r in range(NUM_RESULTS + 1):
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
