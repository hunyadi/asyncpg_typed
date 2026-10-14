import asyncio
import cProfile
import pstats
from typing import NamedTuple

from asyncpg_typed import JsonType, sql
from tests.connection import get_connection


class Resultset(NamedTuple):
    random_json: JsonType
    random_integer: int
    random_string: str


async def async_main() -> None:
    select_sql = sql(
        """--sql
        SELECT
            jsonb_build_object('value', md5(random()::text)) AS random_json,
            (random() * 1000000)::int AS random_integer,
            substr(md5(random()::text), 1, 10) AS random_string
        FROM generate_series(1, 1000000);
        """,
        resultset=Resultset,  # tuple[JsonType, int, str],
    )

    async with get_connection() as conn:
        await select_sql.fetch(conn)


if __name__ == "__main__":
    with cProfile.Profile() as profile:
        asyncio.run(async_main())
        pstats.Stats(profile).sort_stats("tottime").print_stats(20)
