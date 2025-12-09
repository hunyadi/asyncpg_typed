"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

import enum
import sys
import unittest
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from random import randint, sample
from types import UnionType
from typing import Any
from uuid import UUID, uuid4

from asyncpg_typed import sql
from tests.connection import get_connection


class RollbackException(RuntimeError):
    pass


if sys.version_info < (3, 11):

    class State(str, enum.Enum):
        ACTIVE = "active"
        INACTIVE = "inactive"
else:

    class State(enum.StrEnum):
        ACTIVE = "active"
        INACTIVE = "inactive"


class TestDataTypes(unittest.IsolatedAsyncioTestCase):
    async def test_numeric_types(self) -> None:
        create_sql = sql(
            """
            --sql
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
            --sql
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
            --sql
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
            --sql
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
            args=tuple[UUID, str | None, str],
        )

        select_sql = sql(
            """
            --sql
            SELECT uuid_value, json_value, jsonb_value
            FROM composite_types
            ORDER BY id;
            """,
            resultset=tuple[UUID, str | None, str],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record1 = (uuid4(), '{\n"key": [ true, "value", 3 ]\n}', '{"key": [true, "value", 3]}')
            record2 = (uuid4(), None, "[{}]")
            await insert_sql.executemany(conn, [record1, record2])
            self.assertEqual(await select_sql.fetch(conn), [record1, record2])

    async def test_enum_type(self) -> None:
        create_sql = sql(
            """
            --sql
            DO $$ BEGIN
                CREATE TYPE state AS ENUM ('active', 'inactive');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;

            --sql
            CREATE TEMPORARY TABLE enum_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                enum_value state NOT NULL,
                CONSTRAINT pk_sample_data PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO enum_types (enum_value)
            VALUES ($1);
            """,
            args=State,
        )

        select_sql = sql(
            """
            --sql
            SELECT enum_value, enum_value
            FROM enum_types
            ORDER BY id;
            """,
            resultset=tuple[State, State | None],
        )

        value_sql = sql(
            """
            --sql
            SELECT enum_value
            FROM enum_types
            ORDER BY id;
            """,
            resultset=State,
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            await insert_sql.executemany(conn, [(State.ACTIVE,), (State.INACTIVE,)])

            rows = await select_sql.fetch(conn)
            for row in rows:
                for column in row:
                    self.assertIsInstance(column, State)
            self.assertEqual(rows, [(State.ACTIVE, State.ACTIVE), (State.INACTIVE, State.INACTIVE)])

            record = await select_sql.fetchrow(conn)
            self.assertIsNotNone(record)
            if record:
                for column in record:
                    self.assertIsInstance(column, State)
                self.assertEqual(record, (State.ACTIVE, State.ACTIVE))

            value = await value_sql.fetchval(conn)
            self.assertIsInstance(value, State)
            self.assertEqual(value, State.ACTIVE)

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
            resultset=int,
        )

        count_sql = sql(
            """
            --sql
            SELECT COUNT(*) FROM sample_data;
            """,
            resultset=int,
        )

        count_where_sql = sql(
            """
            --sql
            SELECT COUNT(*) FROM sample_data WHERE integer_value > $1;
            """,
            args=int,
            resultset=int,
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
                $1::int, $2::int, $3::int, $4::int, $5::int, $6::int, $7::int, $8::int,
                $1::int, $2::int, $3::int, $4::int, $5::int, $6::int, $7::int, $8::int;
            """,
            args=tuple[int, int, int, int, int, int, int, int],
            resultset=tuple[int, int, int, int, int, int, int, int, int, int, int, int, int, int, int, int],
        )

        async with get_connection() as conn:
            numbers = [randint(-2_147_483_648, 2_147_483_647) for _ in range(8)]
            rows = await passthrough_sql.fetch(conn, *numbers)
            self.assertEqual(rows, [(*numbers, *numbers)])

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
                    """,
                    args=tuple[int, int, int, int, int, int, int, int],
                    resultset=tuple[tuple(params)],  # type: ignore[misc]
                )  # type: ignore[call-overload]

                rows = await passthrough_sql.fetch(conn, *args)
                resultset: list[int | None] = [i for i in args]
                resultset[index] = None
                self.assertEqual(rows, [tuple(resultset)])


if __name__ == "__main__":
    unittest.main()
