"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

import re
import unittest
from io import StringIO
from pathlib import Path
from typing import TextIO


def _args_and_results(p: int, r: int) -> str:
    items: list[str] = []
    items.extend(f"P{k + 1}" for k in range(p))
    items.extend(f"R{k + 1}" for k in range(r))
    if items:
        return f"[{', '.join(items)}]"
    else:
        return ""


def _args(p: int) -> str:
    return _args_and_results(p, 0)


def _results(r: int) -> str:
    return _args_and_results(0, r)


def _params(p: int) -> str:
    if p > 0:
        return ", " + ", ".join(f"arg{k + 1}: P{k + 1}" for k in range(p))
    else:
        return ""


def _typespec(p: int, r: int) -> str:
    params: list[str] = ["*"]
    if p > 0:
        params.append(f"args: type[tuple{_args(p)}]")
    if r > 0:
        params.append(f"resultset: type[tuple{_results(r)}]")
    if len(params) > 1:
        return f", {', '.join(params)}" if params else ""
    else:
        return ""


def write_code(out: TextIO, *, use_modern_generic_syntax: bool = False) -> None:
    NUM_ARGS = 8
    NUM_RESULTS = 8

    if not use_modern_generic_syntax:
        for p in range(1, NUM_ARGS + 1):
            print(f'P{p} = TypeVar("P{p}")', file=out)

        for r in range(1, NUM_RESULTS + 1):
            print(f'R{r} = TypeVar("R{r}")', file=out)

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
            print(r"    @abstractmethod", file=out)
            print(f"    async def fetchrow(self, connection: Connection{_params(p)}) -> tuple{_results(r)} | None: ...", file=out)
            if r == 1:
                print(r"    @abstractmethod", file=out)
                print(f"    async def fetchval(self, connection: Connection{_params(p)}) -> R{r}: ...", file=out)

    for p in range(NUM_ARGS + 1):
        print(r"@overload", file=out)
        if use_modern_generic_syntax:
            print(f"def sql{_args(p)}(stmt: SQLExpression{_typespec(p, 0)}) -> SQL_P{p}{_args(p)}: ...", file=out)
        else:
            print(f"def sql(stmt: SQLExpression{_typespec(p, 0)}) -> SQL_P{p}{_args(p)}: ...", file=out)

        for r in range(1, NUM_RESULTS + 1):
            print(r"@overload", file=out)
            if use_modern_generic_syntax:
                print(f"def sql{_args_and_results(p, r)}(stmt: SQLExpression{_typespec(p, r)}) -> SQL_P{p}_R{r}{_args_and_results(p, r)}: ...", file=out)
            else:
                print(f"def sql(stmt: SQLExpression{_typespec(p, r)}) -> SQL_P{p}_R{r}{_args_and_results(p, r)}: ...", file=out)


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
