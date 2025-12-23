"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

import unittest
from random import randint, sample
from types import UnionType
from typing import Any

from asyncpg_typed import sql
from tests.connection import get_connection


class RollbackException(RuntimeError):
    pass


class TestSQL(unittest.IsolatedAsyncioTestCase):
    async def test_sql(self) -> None:
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

    async def test_multiple(self) -> None:
        passthrough_sql = sql(
            """
            --sql
            SELECT
                $1::int,  $2::int,  $3::int,  $4::int,  $5::int,  $6::int,  $7::int,  $8::int,
                $9::int, $10::int, $11::int, $12::int, $13::int, $14::int, $15::int, $16::int;
            """,
            args=tuple[int, int, int, int, int, int, int, int, int, int, int, int, int, int, int, int, int],
            resultset=tuple[int, int, int, int, int, int, int, int, int, int, int, int, int, int, int, int],
        )

        async with get_connection() as conn:
            numbers = tuple(randint(-2_147_483_648, 2_147_483_647) for _ in range(16))
            rows = await passthrough_sql.fetch(conn, *numbers)
            self.assertEqual(rows, [numbers])

    async def test_nullable(self) -> None:
        def nullif(a: int, b: int) -> str:
            return f"NULLIF(${a + 1}::int, ${b + 1}::int)"

        args = sample(range(-2_147_483_648, 2_147_483_647), 8)

        async with get_connection() as conn:
            for index in range(8):
                params: list[type[Any] | UnionType] = [int, int, int, int, int, int, int, int]
                params[index] = int | None

                passthrough_sql = sql(  # pyright: ignore[reportUnknownVariableType]
                    f"""
                    --sql
                    SELECT
                        {nullif(0, index)}, {nullif(1, index)}, {nullif(2, index)}, {nullif(3, index)},
                        {nullif(4, index)}, {nullif(5, index)}, {nullif(6, index)}, {nullif(7, index)};
                    """,  # pyright: ignore[reportArgumentType]
                    args=tuple[int, int, int, int, int, int, int, int],
                    resultset=tuple[tuple(params)],  # type: ignore[misc]
                )  # type: ignore[call-overload]

                rows = await passthrough_sql.fetch(conn, *args)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
                resultset: list[int | None] = [i for i in args]
                resultset[index] = None
                self.assertEqual(rows, [tuple(resultset)])


if __name__ == "__main__":
    unittest.main()
