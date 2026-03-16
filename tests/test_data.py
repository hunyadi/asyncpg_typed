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

from asyncpg import Box, Circle, Line, LineSegment, Path, Point, Polygon, Range

from asyncpg_typed import JsonType, sql
from tests.connection import get_connection, set_timestamp_codec

if sys.version_info < (3, 11):

    class State(str, enum.Enum):
        ACTIVE = "active"
        INACTIVE = "inactive"

    class Suit(str, enum.Enum):
        SPADES = "spades"
        HEARTS = "hearts"
        DIAMONDS = "diamonds"
        CLUBS = "clubs"

else:

    class State(enum.StrEnum):
        ACTIVE = "active"
        INACTIVE = "inactive"

    class Suit(enum.StrEnum):
        SPADES = "spades"
        HEARTS = "hearts"
        DIAMONDS = "diamonds"
        CLUBS = "clubs"


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
        select_datetime_sql = sql(
            """
            --sql
            SELECT date_time_value, date_time_zone_value
            FROM datetime_types
            ORDER BY id;
            """,
            resultset=tuple[datetime, datetime],
        )

        now_naive = datetime.now(tz=None)
        now_utc = datetime.now(tz=timezone.utc)
        async with get_connection() as conn:
            await create_sql.execute(conn)
            records = [
                (
                    date.today(),
                    time(0, 0, 0, tzinfo=None),
                    time(23, 59, 59, tzinfo=timezone.utc),
                    now_naive,
                    now_utc,
                    timedelta(days=12, hours=23, minutes=59, seconds=59),
                ),
                (
                    date.today(),
                    time(23, 59, 59, tzinfo=None),
                    time(0, 0, 0, tzinfo=timezone(timedelta(hours=1), "Europe/Budapest")),
                    now_naive,
                    now_utc,
                    timedelta(days=12, hours=23, minutes=59, seconds=59),
                ),
            ]
            await insert_sql.executemany(conn, records)
            self.assertEqual(await select_sql.fetch(conn), records)

            await set_timestamp_codec(conn)
            records_utc = [
                (
                    now_naive.replace(tzinfo=timezone.utc),
                    now_utc,
                ),
                (
                    now_naive.replace(tzinfo=timezone.utc),
                    now_utc,
                ),
            ]
            self.assertEqual(await select_datetime_sql.fetch(conn), records_utc)

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

    async def test_uuid_type(self) -> None:
        create_sql = sql(
            """
            --sql
            CREATE TEMPORARY TABLE uuid_type(
                id bigint GENERATED ALWAYS AS IDENTITY,
                uuid_value uuid NOT NULL,
                CONSTRAINT pk_uuid_type PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO uuid_type (uuid_value) VALUES ($1);
            """,
            arg=UUID,
        )

        select_sql = sql(
            """
            --sql
            SELECT uuid_value FROM uuid_type ORDER BY id;
            """,
            result=UUID,
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            records = [(uuid4(),), (uuid4(),), (uuid4(),), (uuid4(),)]
            await insert_sql.executemany(conn, records)
            self.assertEqual(await select_sql.fetch(conn), records)

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
                json_value json,
                jsonb_value jsonb NOT NULL,
                CONSTRAINT pk_json_type PRIMARY KEY (id)
            );
            """
        )

        insert_str_sql = sql(
            """
            --sql
            INSERT INTO json_type (json_value, jsonb_value)
            VALUES ($1, $2);
            """,
            args=tuple[str | None, str],
        )

        insert_json_sql = sql(
            """
            --sql
            INSERT INTO json_type (json_value, jsonb_value)
            VALUES ($1, $2);
            """,
            args=tuple[JsonType, JsonType],
        )

        select_str_sql = sql(
            """
            --sql
            SELECT json_value, jsonb_value
            FROM json_type
            ORDER BY id;
            """,
            resultset=tuple[str | None, str],
        )

        select_json_sql = sql(
            """
            --sql
            SELECT json_value, jsonb_value
            FROM json_type
            ORDER BY id;
            """,
            resultset=tuple[JsonType, JsonType],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)

            pretty_json = '{\n"key": [ true, "value", 3 ]\n}'
            standard_json = '{"key": [true, "value", 3]}'
            compact_json = '{"key":[true,"value",3]}'
            json_value: JsonType = {"key": [True, "value", 3]}
            await insert_str_sql.executemany(
                conn,
                [
                    (pretty_json, pretty_json),
                    (None, "[{}]"),
                ],
            )
            await insert_json_sql.executemany(
                conn,
                [
                    (json_value, json_value),
                    (None, [{}]),
                ],
            )
            self.assertEqual(
                await select_str_sql.fetch(conn),
                [
                    # PostgreSQL `json` preserves whitespace, `jsonb` converts to standard representation
                    (pretty_json, standard_json),
                    (None, "[{}]"),
                    # when Python `JsonType` is serialized, it uses the most compact representation, which is retained by `json` but not `jsonb`
                    (compact_json, standard_json),
                    (None, "[{}]"),
                ],
            )
            self.assertEqual(
                await select_json_sql.fetch(conn),
                [
                    (json_value, json_value),
                    (None, [{}]),
                    (json_value, json_value),
                    (None, [{}]),
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

    async def test_str_enum_type(self) -> None:
        create_sql = sql(
            """
            --sql
            DO $$ BEGIN
                CREATE TYPE state AS ENUM ('active', 'inactive');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;

            --sql
            CREATE TEMPORARY TABLE str_enum_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                enum_value state NOT NULL,
                string_value varchar(64) NOT NULL,
                text_value text NOT NULL,
                CONSTRAINT pk_str_enum_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO str_enum_types (enum_value, string_value, text_value)
            VALUES ($1, $2, $3);
            """,
            args=tuple[State, State, State],
        )

        select_sql = sql(
            """
            --sql
            SELECT enum_value, enum_value, string_value, string_value, text_value, text_value
            FROM str_enum_types
            ORDER BY id;
            """,
            resultset=tuple[State, State | None, State, State | None, State, State | None],
        )

        value_sql = sql(
            """
            --sql
            SELECT enum_value
            FROM str_enum_types
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

    async def test_enum_type(self) -> None:
        create_sql = sql(
            """
            --sql
            DO $$ BEGIN
                CREATE TYPE suit AS ENUM ('spades', 'hearts', 'diamonds', 'clubs');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;

            --sql
            CREATE TEMPORARY TABLE enum_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                enum_value suit NOT NULL,
                CONSTRAINT pk_enum_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO enum_types (enum_value) VALUES ($1);
            """,
            arg=Suit,
        )

        select_sql = sql(
            """
            --sql
            SELECT enum_value FROM enum_types ORDER BY id;
            """,
            result=Suit,
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            await insert_sql.executemany(conn, [(Suit.SPADES,), (Suit.HEARTS,), (Suit.DIAMONDS,), (Suit.CLUBS,)])

            rows = await select_sql.fetch(conn)
            for row in rows:
                for column in row:
                    self.assertIsInstance(column, Suit)
            self.assertEqual(rows, [(Suit.SPADES,), (Suit.HEARTS,), (Suit.DIAMONDS,), (Suit.CLUBS,)])

    async def test_geometric_types(self) -> None:
        create_sql = sql(
            """
            --sql
            CREATE TEMPORARY TABLE geometric_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                point_value point,
                line_value line,
                segment_value lseg,
                box_value box,
                path_value path,
                polygon_value polygon,
                circle_value circle,
                CONSTRAINT pk_geometric_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO geometric_types (point_value, line_value, segment_value, box_value, path_value, polygon_value, circle_value)
            VALUES ($1, $2, $3, $4, $5, $6, $7);
            """,
            args=tuple[Point, Line, LineSegment, Box, Path, Polygon, Circle],
        )

        select_sql = sql(
            """
            --sql
            SELECT point_value, line_value, segment_value, box_value, path_value, polygon_value, circle_value
            FROM geometric_types
            ORDER BY id;
            """,
            resultset=tuple[Point, Line, LineSegment, Box, Path, Polygon, Circle],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record = (
                Point(1.5, 2.5),
                Line(1.5, 2.5, 3.5),
                LineSegment(Point(1.5, 2.5), Point(3.5, 4.5)),
                Box(Point(0.25, 0.75), Point(-0.25, -0.75)),
                Path(Point(0, 0), Point(0, 1), Point(1, 1), Point(1, 0), is_closed=True),
                Polygon(Point(0, 0), Point(0, 1), Point(1, 1), Point(1, 0)),
                Circle(Point(1.5, 2.5), 3.5),
            )
            await insert_sql.executemany(conn, [record])
            self.assertEqual(await select_sql.fetch(conn), [record])

    async def test_range_types(self) -> None:
        create_sql = sql(
            """
            --sql
            CREATE TEMPORARY TABLE range_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                int_range int4range,
                big_range int8range,
                decimal_range numrange,
                date_time_range tsrange,
                date_time_zone_range tstzrange,
                date_range daterange,
                int_multi_range int4multirange,
                big_multi_range int8multirange,
                decimal_multi_range nummultirange,
                date_time_multi_range tsmultirange,
                date_time_zone_multi_range tstzmultirange,
                date_multi_range datemultirange,
                CONSTRAINT pk_range_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO range_types (
                int_range, big_range, decimal_range, date_time_range, date_time_zone_range, date_range,
                int_multi_range, big_multi_range, decimal_multi_range, date_time_multi_range, date_time_zone_multi_range, date_multi_range
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12);
            """,
            args=tuple[Range[int], Range[int], Range[Decimal], Range[datetime], Range[datetime], Range[date], list[Range[int]], list[Range[int]], list[Range[Decimal]], list[Range[datetime]], list[Range[datetime]], list[Range[date]]],
        )

        select_sql = sql(
            """
            --sql
            SELECT
                int_range, big_range, decimal_range, date_time_range, date_time_zone_range, date_range,
                int_multi_range, big_multi_range, decimal_multi_range, date_time_multi_range, date_time_zone_multi_range, date_multi_range
            FROM range_types
            ORDER BY id;
            """,
            resultset=tuple[Range[int], Range[int], Range[Decimal], Range[datetime], Range[datetime], Range[date], list[Range[int]], list[Range[int]], list[Range[Decimal]], list[Range[datetime]], list[Range[datetime]], list[Range[date]]],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record = (
                Range(-2_147_483_648, 2_147_483_647),
                Range(-9_223_372_036_854_775_808, 9_223_372_036_854_775_807),
                Range(Decimal("-0.99"), Decimal("0.99")),
                Range(datetime(1984, 1, 1, 0, 0, 0), datetime(1990, 10, 23, 23, 59, 59)),
                Range(datetime(1984, 1, 1, 0, 0, 0, tzinfo=timezone.utc), datetime(1990, 10, 23, 23, 59, 59, tzinfo=timezone.utc)),
                Range(date(1984, 1, 1), date(1990, 10, 23)),
                [Range(-2_147_483_648, -1), Range(1, 2_147_483_647)],
                [Range(-9_223_372_036_854_775_808, -1), Range(1, 9_223_372_036_854_775_807)],
                [Range(Decimal("0.1"), Decimal("0.2")), Range(Decimal("0.3"), Decimal("0.4")), Range(Decimal("0.5"), Decimal("0.6"))],
                [Range(datetime(1982, 10, 23, 1, 2, 3), datetime(1982, 10, 24, 10, 20, 30)), Range(datetime(1984, 1, 1, 0, 0, 0), datetime(1990, 8, 12, 23, 59, 59))],
                [Range(datetime(1984, 1, 1, 0, 0, 0, tzinfo=timezone.utc), datetime(1990, 10, 23, 23, 59, 59, tzinfo=timezone.utc))],
                [Range(date(1984, 1, 1), date(1990, 10, 23)), Range(date(2000, 1, 1), date(2022, 10, 23))],
            )
            await insert_sql.executemany(conn, [record])
            self.assertEqual(await select_sql.fetch(conn), [record])

    async def test_array_types(self) -> None:
        create_sql = sql(
            """
            --sql
            CREATE TEMPORARY TABLE array_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                boolean_array boolean[] NOT NULL,
                small_array smallint[] NOT NULL,
                integer_array integer[] NOT NULL,
                big_array bigint[] NOT NULL,
                decimal_array decimal[] NOT NULL,
                real_array real[] NOT NULL,
                double_array double precision[] NOT NULL,
                text_array text[] NOT NULL,
                CONSTRAINT pk_array_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO array_types (boolean_array, small_array, integer_array, big_array, decimal_array, real_array, double_array, text_array)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
            """,
            args=tuple[list[bool], list[int], list[int], list[int], list[Decimal], list[float], list[float], list[str]],
        )

        select_sql = sql(
            """
            --sql
            SELECT boolean_array, small_array, integer_array, big_array, decimal_array, real_array, double_array, text_array
            FROM array_types
            ORDER BY id;
            """,
            resultset=tuple[list[bool], list[int], list[int], list[int], list[Decimal], list[float], list[float], list[str]],
        )

        async with get_connection() as conn:
            await create_sql.execute(conn)
            record: tuple[list[bool], list[int], list[int], list[int], list[Decimal], list[float], list[float], list[str]] = (
                [False, True, True],
                [-32_768, 0, 1, 2, 3, 4, 32_767],
                [-2_147_483_648, 0, 1, 2, 2_147_483_647],
                [-9_223_372_036_854_775_808, 0, 9_223_372_036_854_775_807],
                [Decimal("0.1993"), Decimal("0.1997"), Decimal("0.2026")],
                [-float("inf"), 0.0, float("inf")],
                [-float("inf"), -0.5, 0.0, 0.5, float("inf")],
                ["a", "b", "c"],
            )
            await insert_sql.execute(conn, *record)
            self.assertEqual(await select_sql.fetchrow(conn), record)


if __name__ == "__main__":
    unittest.main()
