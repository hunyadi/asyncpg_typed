"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import asyncpg

POSTGRESQL_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


def encode_timestamp(dt: datetime) -> tuple[int]:
    "Encodes a timezone-aware datetime as a tuple of microseconds since the PostgreSQL epoch."

    delta = dt - POSTGRESQL_EPOCH
    total_microseconds = (24 * 3600 * 1_000_000) * delta.days + 1_000_000 * delta.seconds + delta.microseconds
    return (total_microseconds,)


def decode_timestamp(tp: tuple[int]) -> datetime:
    "Decodes a tuple of microseconds since the PostgreSQL epoch into a timezone-aware datetime."

    (total_microseconds,) = tp
    return POSTGRESQL_EPOCH + timedelta(microseconds=total_microseconds)


async def set_timestamp_codec(conn: asyncpg.Connection) -> None:
    "Registers a custom type codec for the connection so that timezone-aware Python type `datetime` is encoded and decoded from PostgreSQL type `timestamp`."

    await conn.set_type_codec(
        "timestamp",
        encoder=encode_timestamp,
        decoder=decode_timestamp,
        schema="pg_catalog",
        format="tuple",
    )


@asynccontextmanager
async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(host="localhost", port=5432, user="postgres", password="postgres")
    try:
        await conn.execute(
            """--sql
            SET TIME ZONE 'UTC';
            CREATE EXTENSION IF NOT EXISTS vector;
            """
        )
        yield conn
    finally:
        await conn.close()
