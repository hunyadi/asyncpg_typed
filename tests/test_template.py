"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

# This test suite requires Python 3.14 or later

import sys
import unittest

from asyncpg_typed import sql
from tests.connection import get_connection

if sys.version_info >= (3, 14):
    from string.templatelib import Interpolation, Template


@unittest.skipUnless(sys.version_info >= (3, 14), "requires Python 3.14 or later")
class TestTemplate(unittest.IsolatedAsyncioTestCase):
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
            # use template object (as opposed to t-string) to ensure syntax compatibility with earlier versions of Python
            Template("INSERT INTO sample_data (boolean_value, integer_value, string_value) VALUES (", Interpolation(1), ", ", Interpolation(2), ", ", Interpolation(3), ");"),
            args=tuple[bool, int, str | None],
        )

        select_where_sql = sql(
            # use template object (as opposed to t-string) to ensure syntax compatibility with earlier versions of Python
            Template("SELECT boolean_value, integer_value, string_value FROM sample_data WHERE boolean_value = ", Interpolation(1), " AND integer_value > ", Interpolation(2), " ORDER BY integer_value;"),
            args=tuple[bool, int],
            resultset=tuple[bool, int, str | None],
        )

        async with get_connection() as conn:
            await conn.execute("SELECT 1")

            await create_sql.execute(conn)
            await insert_sql.execute(conn, False, 23, "twenty-three")
            await insert_sql.executemany(conn, [(False, 1, "one"), (True, 2, "two"), (False, 3, "three"), (True, 64, None)])

            self.assertEqual(await select_where_sql.fetch(conn, False, 2), [(False, 3, "three"), (False, 23, "twenty-three")])
            self.assertEqual(await select_where_sql.fetch(conn, True, 32), [(True, 64, None)])


if __name__ == "__main__":
    unittest.main()
