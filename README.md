# Type-safe queries for asyncpg

[asyncpg](https://magicstack.github.io/asyncpg/current/) is a high-performance database client to connect to a PostgreSQL server, and execute SQL statements using the async/await paradigm in Python. The library exposes a `Connection` object, which has methods like `execute` and `fetch` that run SQL queries against the database. Unfortunately, these methods take the query as a plain `str`, arguments as `object`, and the resultset is exposed as a `Record`, which is a `tuple`/`dict` hybrid whose `get` and indexer have a return type of `Any`. There is no mechanism to check compatibility of input or output arguments, even if their types are preliminarily known.

This Python library provides "compile-time" validation for SQL queries that linters and type checkers can enforce. By creating a generic `SQL` object and associating input and output type information with the query, the signatures of `execute` and `fetch` reveal the exact expected and returned types.

## Motivating example

```python
# create a typed object, setting expected and returned types
select_where_sql = sql(
    """--sql
    SELECT boolean_value, integer_value, string_value
    FROM sample_data
    WHERE boolean_value = $1 AND integer_value > $2
    ORDER BY integer_value;
    """,
    args=tuple[bool, int],
    resultset=tuple[bool, int, str | None],
)

conn = await asyncpg.connect(host="localhost", port=5432, user="postgres", password="postgres")
try:
    # ✅ Valid signature
    rows = await select_where_sql.fetch(conn, False, 2)

    # ✅ Type of "rows" is "list[tuple[bool, int, str | None]]"
    reveal_type(rows)

    # ⚠️ Argument missing for parameter "arg2"
    rows = await select_where_sql.fetch(conn, False)

    # ⚠️ Argument of type "float" cannot be assigned to parameter "arg2" of type "int" in function "fetch"; "float" is not assignable to "int"
    rows = await select_where_sql.fetch(conn, False, 3.14)

finally:
    await conn.close()
```

## Run-time behavior

When a call such as `sql.executemany(conn, records)` or `sql.fetch(conn, param1, param2)` is made on a `SQL` object at run time, the library invokes `connection.prepare(sql)` to create a `PreparedStatement` and compares the actual statement signature against the expected Python types. Unfortunately, PostgreSQL doesn't propagate nullability via prepared statements: resultset types that are declared as required (e.g. `T` as opposed to `T | None`) are validated at run time.
