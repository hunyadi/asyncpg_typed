"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg


@asynccontextmanager
async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(host="localhost", port=5432, user="postgres", password="postgres")
    try:
        yield conn
    finally:
        await conn.close()
