"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import asyncpg

from asyncpg_typed import JsonType, sql


class RollbackException(RuntimeError):
    pass


@asynccontextmanager
async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(host="localhost", port=5432, user="postgres", password="postgres")
    try:
        yield conn
    finally:
        await conn.close()


class TestDataTypes(unittest.IsolatedAsyncioTestCase):
    async def test_numeric_types(self) -> None:
        create_sql = sql(
            """
            ---sql
            CREATE TEMPORARY TABLE numeric_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                boolean_value boolean NOT NULL,
                small_value smallint NOT NULL,
                integer_value integer NOT NULL,
                big_value bigint NOT NULL,
                decimal_value decimal NOT NULL,
                real_value real NOT NULL,
                double_value double precision NOT NULL,
                CONSTRAINT pk_numeric_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO numeric_types (boolean_value, small_value, integer_value, big_value, decimal_value, real_value, double_value)
            VALUES ($1, $2, $3, $4, $5, $6, $7);
            """,
            args=tuple[bool, int, int, int, Decimal, float, float],
        )

        select_sql = sql(
            """
            --sql
            SELECT boolean_value, small_value, integer_value, big_value, decimal_value, real_value, double_value
            FROM numeric_types
            ORDER BY id;
            """,
            resultset=tuple[bool, int, int, int, Decimal, float, float],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record_min = (False, -32_768, -2_147_483_648, -9_223_372_036_854_775_808, Decimal("0.1993"), -float("inf"), -float("inf"))
            record_max = (True, 32_767, 2_147_483_647, 9_223_372_036_854_775_807, Decimal("0.1997"), float("inf"), float("inf"))
            await insert_sql.executemany(conn, [record_min, record_max])
            self.assertEqual(await select_sql.fetch(conn), [record_min, record_max])

    async def test_datetime_types(self) -> None:
        create_sql = sql(
            """
            ---sql
            CREATE TEMPORARY TABLE datetime_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                date_value date NOT NULL,
                time_value time without time zone NOT NULL,
                time_zone_value time with time zone NOT NULL,
                date_time_value timestamp without time zone NOT NULL,
                date_time_zone_value timestamp with time zone NOT NULL,
                CONSTRAINT pk_datetime_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO datetime_types (date_value, time_value, time_zone_value, date_time_value, date_time_zone_value)
            VALUES ($1, $2, $3, $4, $5);
            """,
            args=tuple[date, time, time, datetime, datetime],
        )

        select_sql = sql(
            """
            --sql
            SELECT date_value, time_value, time_zone_value, date_time_value, date_time_zone_value
            FROM datetime_types
            ORDER BY id;
            """,
            resultset=tuple[date, time, time, datetime, datetime],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record = (
                date.today(),
                time(23, 59, 59, tzinfo=None),
                time(23, 59, 59, tzinfo=timezone(timedelta(hours=1), "Europe/Budapest")),
                datetime.now(tz=None),
                datetime.now(tz=timezone.utc),
            )
            await insert_sql.executemany(conn, [record])
            self.assertEqual(await select_sql.fetch(conn), [record])

    async def test_sequence_types(self) -> None:
        create_sql = sql(
            """
            ---sql
            CREATE TEMPORARY TABLE sequence_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                bytes_value bytea NOT NULL,
                char_value char(4) NOT NULL,
                string_value varchar(63) NOT NULL,
                text_value text NOT NULL,
                CONSTRAINT pk_sequence_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO sequence_types (bytes_value, char_value, string_value, text_value)
            VALUES ($1, $2, $3, $4);
            """,
            args=tuple[bytes, str, str, str],
        )

        select_sql = sql(
            """
            --sql
            SELECT bytes_value, char_value, string_value, text_value
            FROM sequence_types
            ORDER BY id;
            """,
            resultset=tuple[bytes, str, str, str],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record = (b"zero", "four", "twenty-three", "a long string")
            await insert_sql.executemany(conn, [record])
            self.assertEqual(await select_sql.fetch(conn), [record])

    async def test_composite_type(self) -> None:
        create_sql = sql(
            """
            ---sql
            CREATE TEMPORARY TABLE composite_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                uuid_value uuid NOT NULL,
                json_value json,
                jsonb_value jsonb NOT NULL,
                CONSTRAINT pk_composite_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO composite_types (uuid_value, json_value, jsonb_value)
            VALUES ($1, $2, $3);
            """,
            args=tuple[UUID, JsonType | None, JsonType],
        )

        select_sql = sql(
            """
            --sql
            SELECT uuid_value, json_value, jsonb_value
            FROM composite_types
            ORDER BY id;
            """,
            resultset=tuple[UUID, JsonType | None, JsonType],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record1 = (uuid4(), '{\n"key": [ true, "value", 3 ]\n}', '{"key": [true, "value", 3]}')
            record2 = (uuid4(), None, "[{}]")
            await insert_sql.executemany(conn, [record1, record2])
            self.assertEqual(await select_sql.fetch(conn), [record1, record2])

    async def test_sql(self) -> None:
        create_sql = sql(
            """
            ---sql
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

        count_sql = sql(
            """
            --sql
            SELECT COUNT(*) FROM sample_data;
            """,
            resultset=tuple[int],  # type: ignore[arg-type, var-annotated]
        )

        async with get_connection() as conn:
            await conn.execute("SELECT 1")

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

            count = await count_sql.fetchval(conn)
            self.assertIsInstance(count, int)
            self.assertEqual(count, 5)


if __name__ == "__main__":
    unittest.main()
