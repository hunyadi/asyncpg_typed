"""
Type-safe queries for asyncpg.

:see: https://github.com/hunyadi/asyncpg_typed
"""

import unittest
from contextlib import asynccontextmanager
from random import random

import asyncpg
from asyncpg_vector import HalfVector, Vector, register_vector

from asyncpg_typed import sql


class RollbackException(RuntimeError):
    pass


@asynccontextmanager
async def get_connection():
    conn = await asyncpg.connect(host="localhost", port=5432, user="postgres", password="postgres")
    try:
        yield conn
    finally:
        await conn.close()


class TestConnection(unittest.IsolatedAsyncioTestCase):
    async def test_vector_type(self) -> None:
        create_sql = sql(
            """
            ---sql
            CREATE EXTENSION IF NOT EXISTS vector;

            --sql
            CREATE TEMPORARY TABLE vector_types(
                id bigint GENERATED ALWAYS AS IDENTITY,
                embedding vector(1536),
                half_embedding halfvec(1536) NOT NULL,
                CONSTRAINT pk_composite_types PRIMARY KEY (id)
            );
            """
        )

        insert_sql = sql(
            """
            --sql
            INSERT INTO vector_types (embedding, half_embedding)
            VALUES ($1, $2);
            """,
            args=tuple[Vector | None, HalfVector],
        )

        select_sql = sql(
            """
            --sql
            SELECT embedding, half_embedding
            FROM vector_types
            ORDER BY id;
            """,
            resultset=tuple[Vector | None, HalfVector],
        )

        random_vector = [random() for _ in range(1536)]
        zero_vector = [0 for _ in range(1536)]

        async with get_connection() as conn:
            await create_sql.execute(conn)
            await register_vector(conn)
            record1 = (Vector.from_float_list(random_vector), HalfVector.from_float_list(random_vector))
            record2 = (None, HalfVector.from_float_list(zero_vector))
            await insert_sql.executemany(conn, [record1, record2])
            self.assertEqual(await select_sql.fetch(conn), [record1, record2])


if __name__ == "__main__":
    unittest.main()
