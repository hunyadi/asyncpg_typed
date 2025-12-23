"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

import enum
import sys
import unittest
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
from uuid import UUID, uuid4

from asyncpg_typed import JsonType, sql
from tests.connection import get_connection

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
                time_delta_value interval NOT NULL,
                CONSTRAINT pk_datetime_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO datetime_types (date_value, time_value, time_zone_value, date_time_value, date_time_zone_value, time_delta_value)
            VALUES ($1, $2, $3, $4, $5, $6);
            """,
            args=tuple[date, time, time, datetime, datetime, timedelta],
        )

        select_sql = sql(
            """
            --sql
            SELECT date_value, time_value, time_zone_value, date_time_value, date_time_zone_value, time_delta_value
            FROM datetime_types
            ORDER BY id;
            """,
            resultset=tuple[date, time, time, datetime, datetime, timedelta],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record = (
                date.today(),
                time(23, 59, 59, tzinfo=None),
                time(23, 59, 59, tzinfo=timezone(timedelta(hours=1), "Europe/Budapest")),
                datetime.now(tz=None),
                datetime.now(tz=timezone.utc),
                timedelta(days=12, hours=23, minutes=59, seconds=59),
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

    async def test_inet_type(self) -> None:
        create_sql = sql(
            """
            --sql
            CREATE TEMPORARY TABLE inet_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                cidr_value cidr,
                inet_value inet,
                CONSTRAINT pk_inet_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql_stmt = """
            --sql
            INSERT INTO inet_types (cidr_value, inet_value)
            VALUES ($1, $2);
            """

        select_sql_stmt = """
            --sql
            SELECT cidr_value, inet_value
            FROM inet_types
            ORDER BY id;
            """

        insert_ipv4_sql = sql(
            insert_sql_stmt,
            args=tuple[IPv4Network, IPv4Address],
        )

        select_ipv4_sql = sql(
            select_sql_stmt,
            resultset=tuple[IPv4Network, IPv4Address],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record_ipv4 = (IPv4Network("192.0.2.0/24"), IPv4Address("192.0.2.127"))
            await insert_ipv4_sql.executemany(conn, [record_ipv4])
            result_ipv4 = await select_ipv4_sql.fetchrow(conn)
            if result_ipv4 is not None:
                self.assertEqual(result_ipv4, record_ipv4)
                self.assertIsInstance(result_ipv4[0], IPv4Network)
                self.assertIsInstance(result_ipv4[1], IPv4Address)

        insert_ipv6_sql = sql(
            insert_sql_stmt,
            args=tuple[IPv6Network, IPv6Address],
        )

        select_ipv6_sql = sql(
            select_sql_stmt,
            resultset=tuple[IPv6Network, IPv6Address],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record_ipv6 = (IPv6Network("2001:db8::/32"), IPv6Address("2001:db8:ffff:ffff:ffff:ffff:ffff:ffff"))
            await insert_ipv6_sql.executemany(conn, [record_ipv6])
            result_ipv6 = await select_ipv6_sql.fetchrow(conn)
            if result_ipv6 is not None:
                self.assertEqual(result_ipv6, record_ipv6)
                self.assertIsInstance(result_ipv6[0], IPv6Network)
                self.assertIsInstance(result_ipv6[1], IPv6Address)

        insert_any_sql = sql(
            insert_sql_stmt,
            args=tuple[IPv4Network | IPv6Network, IPv4Address | IPv6Address],
        )

        select_any_sql = sql(
            select_sql_stmt,
            resultset=tuple[IPv4Network | IPv6Network, IPv4Address | IPv6Address],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            records: list[tuple[IPv4Network | IPv6Network, IPv4Address | IPv6Address]] = [
                (IPv4Network("192.0.2.0/24"), IPv4Address("192.0.2.127")),
                (IPv6Network("2001:db8::/32"), IPv6Address("2001:db8:ffff:ffff:ffff:ffff:ffff:ffff")),
            ]
            await insert_any_sql.executemany(conn, records)
            result_any = await select_any_sql.fetch(conn)
            self.assertEqual(result_any, records)
            self.assertIsInstance(result_any[0][0], IPv4Network)
            self.assertIsInstance(result_any[0][1], IPv4Address)
            self.assertIsInstance(result_any[1][0], IPv6Network)
            self.assertIsInstance(result_any[1][1], IPv6Address)

    async def test_macaddr_type(self) -> None:
        create_sql = sql(
            """
            --sql
            CREATE TEMPORARY TABLE macaddr_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                macaddr_value macaddr,
                macaddr8_value macaddr8,
                CONSTRAINT pk_macaddr_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO macaddr_types (macaddr_value, macaddr8_value)
            VALUES ($1, $2);
            """,
            args=tuple[str, str],
        )

        select_sql = sql(
            """
            --sql
            SELECT macaddr_value, macaddr8_value
            FROM macaddr_types
            ORDER BY id;
            """,
            resultset=tuple[str, str],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record = ("00:1a:2b:3c:4d:5e", "00:1a:2b:3c:4d:5e:6f:70")
            await insert_sql.executemany(conn, [record])
            self.assertEqual(await select_sql.fetch(conn), [record])

    async def test_json_type(self) -> None:
        create_sql = sql(
            """
            --sql
            CREATE TEMPORARY TABLE json_type(
                id bigint GENERATED ALWAYS AS IDENTITY,
                uuid_value uuid NOT NULL,
                json_value json,
                jsonb_value jsonb NOT NULL,
                CONSTRAINT pk_json_type PRIMARY KEY (id)
            );
            """
        )

        insert_str_sql = sql(
            """
            --sql
            INSERT INTO json_type (uuid_value, json_value, jsonb_value)
            VALUES ($1, $2, $3);
            """,
            args=tuple[UUID, str | None, str],
        )

        insert_json_sql = sql(
            """
            --sql
            INSERT INTO json_type (uuid_value, json_value, jsonb_value)
            VALUES ($1, $2, $3);
            """,
            args=tuple[UUID, JsonType, JsonType],
        )

        select_sql = sql(
            """
            --sql
            SELECT uuid_value, json_value, jsonb_value, jsonb_value
            FROM json_type
            ORDER BY id;
            """,
            resultset=tuple[UUID, str | None, str, JsonType],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            uuid_1, uuid_2, uuid_3, uuid_4 = uuid4(), uuid4(), uuid4(), uuid4()
            pretty_json = '{\n"key": [ true, "value", 3 ]\n}'
            standard_json = '{"key": [true, "value", 3]}'
            await insert_str_sql.executemany(
                conn,
                [
                    (uuid_1, pretty_json, pretty_json),
                    (uuid_2, None, "[{}]"),
                ],
            )
            await insert_json_sql.executemany(
                conn,
                [
                    (uuid_3, pretty_json, pretty_json),
                    (uuid_4, None, "[{}]"),
                ],
            )
            self.assertEqual(
                await select_sql.fetch(conn),
                [
                    (uuid_1, pretty_json, standard_json, {"key": [True, "value", 3]}),
                    (uuid_2, None, "[{}]", [{}]),
                    (uuid_3, pretty_json, standard_json, {"key": [True, "value", 3]}),
                    (uuid_4, None, "[{}]", [{}]),
                ],
            )

    async def test_xml_type(self) -> None:
        create_sql = sql(
            """
            --sql
            CREATE TEMPORARY TABLE xml_type(
                id bigint GENERATED ALWAYS AS IDENTITY,
                uuid_value uuid NOT NULL,
                xml_value xml NOT NULL,
                CONSTRAINT pk_xml_type PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO xml_type (uuid_value, xml_value)
            VALUES ($1, $2);
            """,
            args=tuple[UUID, str],
        )

        select_sql = sql(
            """
            --sql
            SELECT uuid_value, xml_value
            FROM xml_type
            ORDER BY id;
            """,
            resultset=tuple[UUID, str],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record = (uuid4(), "<book><title>Manual</title><chapter>...</chapter></book>")
            await insert_sql.execute(conn, *record)
            self.assertEqual(await select_sql.fetch(conn), [record])

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
                string_value varchar(64) NOT NULL,
                text_value text NOT NULL,
                CONSTRAINT pk_sample_data PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO enum_types (enum_value, string_value, text_value)
            VALUES ($1, $2, $3);
            """,
            args=tuple[State, State, State],
        )

        select_sql = sql(
            """
            --sql
            SELECT enum_value, enum_value, string_value, string_value, text_value, text_value
            FROM enum_types
            ORDER BY id;
            """,
            resultset=tuple[State, State | None, State, State | None, State, State | None],
        )

        value_sql = sql(
            """
            --sql
            SELECT enum_value
            FROM enum_types
            ORDER BY id;
            """,
            result=State,
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            await insert_sql.executemany(conn, [(State.ACTIVE, State.ACTIVE, State.ACTIVE), (State.INACTIVE, State.INACTIVE, State.INACTIVE)])

            rows = await select_sql.fetch(conn)
            for row in rows:
                for column in row:
                    self.assertIsInstance(column, State)
            self.assertEqual(rows, [(State.ACTIVE, State.ACTIVE) * 3, (State.INACTIVE, State.INACTIVE) * 3])

            record = await select_sql.fetchrow(conn)
            self.assertIsNotNone(record)
            if record:
                for column in record:
                    self.assertIsInstance(column, State)
                self.assertEqual(record, (State.ACTIVE, State.ACTIVE) * 3)

            value = await value_sql.fetchval(conn)
            self.assertIsInstance(value, State)
            self.assertEqual(value, State.ACTIVE)


if __name__ == "__main__":
    unittest.main()
