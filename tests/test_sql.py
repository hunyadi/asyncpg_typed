"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

import unittest
from random import randint, sample
from types import UnionType
from typing import Any, NamedTuple

from asyncpg_typed import CountMismatchError, JsonType, NameMismatchError, NoneTypeError, TypeMismatchError, sql, unsafe_sql
from tests.connection import get_connection


class TestSQL(unittest.IsolatedAsyncioTestCase):
    async def test_namedtuple(self) -> None:
        class BoolIntStringTuple(NamedTuple):
            boolean_value: bool
            integer_value: int
            string_value: str | None

        create_sql = sql(
            """
            --sql
            CREATE TEMPORARY TABLE sample_data(
                id bigint GENERATED ALWAYS AS IDENTITY,
                boolean_value bool NOT NULL,
                integer_value int NOT NULL,
                string_value varchar(63),
                CONSTRAINT pk_sample_data PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO sample_data (boolean_value, integer_value, string_value)
            VALUES ($1, $2, $3);
            """,
            args=BoolIntStringTuple,
        )

        select_sql = sql(
            """
            --sql
            SELECT boolean_value, integer_value, string_value
            FROM sample_data
            WHERE integer_value < 100
            ORDER BY integer_value;
            """,
            resultset=BoolIntStringTuple,
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            await insert_sql.executemany(conn, [(False, 1, "one"), (True, 2, "two"), (False, 3, "three"), (False, 23, "twenty-three"), (True, 64, None)])

            rows = await select_sql.fetch(conn)
            for r in rows:
                self.assertIsInstance(r, BoolIntStringTuple)
            self.assertEqual(rows, [(False, 1, "one"), (True, 2, "two"), (False, 3, "three"), (False, 23, "twenty-three"), (True, 64, None)])

            row = await select_sql.fetchrow(conn)
            self.assertIsInstance(row, BoolIntStringTuple)
            if isinstance(row, BoolIntStringTuple):
                self.assertEqual(row.boolean_value, False)
                self.assertEqual(row.integer_value, 1)
                self.assertEqual(row.string_value, "one")

    async def test_converted_namedtuple(self) -> None:
        class BoolJsonTuple(NamedTuple):
            boolean_value: bool
            json_value: JsonType

        create_sql = sql(
            """
            --sql
            CREATE TEMPORARY TABLE sample_data(
                id bigint GENERATED ALWAYS AS IDENTITY,
                boolean_value bool NOT NULL,
                json_value jsonb NOT NULL,
                CONSTRAINT pk_sample_data PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO sample_data (boolean_value, json_value)
            VALUES ($1, $2);
            """,
            args=BoolJsonTuple,
        )

        select_sql = sql(
            """
            --sql
            SELECT boolean_value, json_value
            FROM sample_data
            ORDER BY id;
            """,
            resultset=BoolJsonTuple,
        )

        records = [BoolJsonTuple(True, {"arg": "value"}), BoolJsonTuple(False, {}), BoolJsonTuple(True, {"datetime": "2000-10-23T23:59:59"})]

        async with get_connection() as conn:
            await create_sql.execute(conn)
            await insert_sql.executemany(conn, records)

            rows = await select_sql.fetch(conn)
            for r in rows:
                self.assertIsInstance(r, BoolJsonTuple)
            self.assertEqual(rows, records)

            row = await select_sql.fetchrow(conn)
            self.assertIsInstance(row, BoolJsonTuple)
            if isinstance(row, BoolJsonTuple):
                self.assertEqual(row.boolean_value, True)
                self.assertEqual(row.json_value, {"arg": "value"})

    async def test_mismatch(self) -> None:
        class MismatchedTuple(NamedTuple):
            value: str | None

        select_sql = sql(
            """
            --sql
            SELECT NULL AS val;
            """,
            resultset=MismatchedTuple,
        )

        async with get_connection() as conn:
            with self.assertRaises(NameMismatchError):
                await select_sql.fetch(conn)

    async def test_sql(self) -> None:
        class RollbackException(RuntimeError):
            pass

        create_sql = sql(
            """
            --sql
            CREATE TEMPORARY TABLE sample_data(
                id bigint GENERATED ALWAYS AS IDENTITY,
                boolean_value bool NOT NULL,
                integer_value int NOT NULL,
                string_value varchar(63),
                CONSTRAINT pk_sample_data PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO sample_data (boolean_value, integer_value, string_value)
            VALUES ($1, $2, $3);
            """,
            args=tuple[bool, int, str | None],
        )

        select_sql = sql(
            """
            --sql
            SELECT boolean_value, integer_value, string_value
            FROM sample_data
            WHERE integer_value < 100
            ORDER BY integer_value;
            """,
            resultset=tuple[bool, int, str | None],
        )

        select_where_sql = sql(
            """
            --sql
            SELECT boolean_value, integer_value, string_value
            FROM sample_data
            WHERE boolean_value = $1 AND integer_value > $2
            ORDER BY integer_value;
            """,
            args=tuple[bool, int],
            resultset=tuple[bool, int, str | None],
        )

        select_column_sql = sql(
            """
            --sql
            SELECT integer_value
            FROM sample_data
            ORDER BY integer_value;
            """,
            result=int,
        )

        insert_returning_sql = sql(
            """
            --sql
            INSERT INTO sample_data (boolean_value, integer_value, string_value)
            VALUES ($1, $2, $3)
            RETURNING id;
            """,
            args=tuple[bool, int, str | None],
            result=int,
        )

        count_sql = sql(
            """
            --sql
            SELECT COUNT(*) FROM sample_data;
            """,
            result=int,
        )

        count_where_sql = sql(
            """
            --sql
            SELECT COUNT(*) FROM sample_data WHERE integer_value > $1;
            """,
            arg=int,
            result=int,
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            await insert_sql.execute(conn, False, 23, "twenty-three")
            await insert_sql.executemany(conn, [(False, 1, "one"), (True, 2, "two"), (False, 3, "three"), (True, 64, None)])

            try:
                async with conn.transaction():
                    await insert_sql.execute(conn, False, 45, "forty-five")
                    await insert_sql.execute(conn, False, 67, "sixty-seven")
                    raise RollbackException()
            except RollbackException:
                pass

            self.assertEqual(await select_sql.fetch(conn), [(False, 1, "one"), (True, 2, "two"), (False, 3, "three"), (False, 23, "twenty-three"), (True, 64, None)])
            self.assertEqual(await select_where_sql.fetch(conn, False, 2), [(False, 3, "three"), (False, 23, "twenty-three")])
            self.assertEqual(await select_where_sql.fetchrow(conn, True, 32), (True, 64, None))
            self.assertEqual(await select_column_sql.fetchcol(conn), [1, 2, 3, 23, 64])
            rows = await insert_returning_sql.fetchmany(conn, [(True, 4, "four"), (False, 5, "five"), (True, 6, "six")])
            self.assertEqual(len(rows), 3)
            for row in rows:
                self.assertEqual(len(row), 1)

            count = await count_sql.fetchval(conn)
            self.assertIsInstance(count, int)
            self.assertEqual(count, 8)

            count_where = await count_where_sql.fetchval(conn, 1)
            self.assertIsInstance(count_where, int)
            self.assertEqual(count_where, 7)

    async def test_count(self) -> None:
        select_sql = sql(
            """
            --sql
            SELECT NULL::bigint;
            """,
            resultset=tuple[int | None, int | None],
        )

        async with get_connection() as conn:
            with self.assertRaises(CountMismatchError):
                await select_sql.fetch(conn)

    async def test_type(self) -> None:
        select_sql = sql(
            """
            --sql
            SELECT 'string';
            """,
            result=int,
        )

        async with get_connection() as conn:
            with self.assertRaises(TypeMismatchError):
                await select_sql.fetch(conn)

    async def test_none(self) -> None:
        select_sql = sql(
            """
            --sql
            SELECT NULL::bigint;
            """,
            result=int,
        )

        async with get_connection() as conn:
            with self.assertRaises(NoneTypeError):
                await select_sql.fetch(conn)

    async def test_multiple(self) -> None:
        passthrough_sql = sql(
            """
            --sql
            SELECT
                $1::int,  $2::int,  $3::int,  $4::int,  $5::int,  $6::int,  $7::int,  $8::int,
                $9::int, $10::int, $11::int, $12::int, $13::int, $14::int, $15::int, $16::int;
            """,
            args=tuple[int, int, int, int, int, int, int, int, int, int, int, int, int, int, int, int],
            resultset=tuple[int, int, int, int, int, int, int, int, int, int, int, int, int, int, int, int],
        )

        async with get_connection() as conn:
            numbers = tuple(randint(-2_147_483_648, 2_147_483_647) for _ in range(16))
            rows = await passthrough_sql.fetch(conn, *numbers)
            self.assertEqual(rows, [numbers])

    async def test_nullable(self) -> None:
        "Checks nullability with various combinations of column count and `NULL` value position in the result-set."

        max_count = 10
        args = sample(range(-2_147_483_648, 2_147_483_647), max_count)
        max_value = max(args)

        async with get_connection() as conn:
            for count in range(1, max_count + 1):
                for index in range(count):
                    params: list[type[Any] | UnionType] = [int] * count
                    params[index] = int | None

                    # `NULL` for the active slot (but consuming all input parameters), or the input number otherwise
                    expr: list[str] = [f"${i + 1}::int" for i in range(count)]
                    expr[index] = f"NULLIF(GREATEST({', '.join(f'${i + 1}::int' for i in range(max_count))}), {max_value})"

                    passthrough_sql = unsafe_sql(
                        f"SELECT {', '.join(expr)};",
                        args=tuple[int, int, int, int, int, int, int, int, int, int],
                        resultset=tuple[tuple(params)],  # type: ignore[misc]
                    )  # type: ignore[call-overload]

                    rows = await passthrough_sql.fetch(conn, *args)
                    resultset: list[int | None] = [args[i] for i in range(count)]
                    resultset[index] = None
                    self.assertEqual(rows, [tuple(resultset)])

    async def test_conversion(self) -> None:
        "Checks conversion with various combinations of column count and converted value position in the result-set."

        async with get_connection() as conn:
            max_count = 10
            for count in range(1, max_count + 1):
                for index in range(count):
                    params: list[type[Any] | UnionType] = [str | None] * count
                    params[index] = JsonType

                    expr: list[str] = ["NULL"] * count
                    expr[index] = f"jsonb_build_object('value', {index})"

                    passthrough_sql = unsafe_sql(
                        f"SELECT {', '.join(expr)};",
                        resultset=tuple[tuple(params)],  # type: ignore[misc]
                    )  # type: ignore[call-overload]

                    rows = await passthrough_sql.fetch(conn)
                    resultset: list[str | JsonType] = [None for _ in range(count)]
                    resultset[index] = {"value": index}
                    self.assertEqual(rows, [tuple(resultset)])

    async def test_set_type_codec(self) -> None:
        create_type_sql = """
            DO $$ BEGIN
                CREATE TYPE complex AS (
                    r double precision,
                    i double precision
                );
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """

        create_sql = sql(
            """
            --sql
            CREATE TEMPORARY TABLE complex_type(
                id bigint GENERATED ALWAYS AS IDENTITY,
                complex_value complex,
                CONSTRAINT pk_complex_type PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO complex_type (complex_value)
            VALUES ($1);
            """,
            arg=complex,
        )

        select_sql = sql(
            """
            --sql
            SELECT complex_value
            FROM complex_type
            ORDER BY id;
            """,
            result=complex,
        )

        def _complex_encoder(c: complex) -> tuple[float, float]:
            return c.real, c.imag

        def _complex_decoder(t: tuple[float, float]) -> complex:
            return complex(t[0], t[1])

        async with get_connection() as conn:
            await conn.execute(create_type_sql)
            await conn.set_type_codec(
                "complex",
                encoder=_complex_encoder,
                decoder=_complex_decoder,
                format="tuple",
            )
            await create_sql.execute(conn)
            records = [(1 + 2j,), (3 + 4j,), (5 + 6j,)]
            await insert_sql.executemany(conn, records)
            self.assertEqual(await select_sql.fetch(conn), records)


if __name__ == "__main__":
    unittest.main()
