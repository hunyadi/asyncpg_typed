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


## Syntax

### Creating a SQL object

Instantiate a SQL object with the `sql` function:

```python
def sql(
    stmt: LiteralString | string.templatelib.Template,
    *,
    args: None | type[tuple[P1, P2]] | type[tuple[P1, P2, P3]] | ... = None,
    resultset: None | type[tuple[R1, R2]] | type[tuple[R1, R2, R3]] | ... = None,
    arg: None | type[P] = None,
    result: None | type[R] = None,
) -> _SQL: ...
```

The parameter `stmt` represents a SQL expression, either as a literal string or a template (i.e. a *t-string*).

If the expression is a string, it can have PostgreSQL parameter placeholders such as `$1`, `$2` or `$3`:

```python
"INSERT INTO table_name (col_1, col_2, col_3) VALUES ($1, $2, $3);"
```

If the expression is a *t-string*, it can have replacement fields that evaluate to integers:

```python
t"INSERT INTO table_name (col_1, col_2, col_3) VALUES ({1}, {2}, {3});"
```

The parameters `args` and `resultset` take a `tuple` of several types `Px` or `Rx`, each of which may be any of the following:

* (required) simple type
* optional simple type (`T | None`)

Simple types include:

* `bool`
* `int`
* `float`
* `decimal.Decimal`
* `datetime.date`
* `datetime.time`
* `datetime.datetime`
* `str`
* `bytes`
* `uuid.UUID`
* a user-defined class that derives from `StrEnum`

Types are grouped together with `tuple`:

```python
tuple[bool, int, str | None]
```

The parameters `arg` and `result` take a single type `P` or `R`. Passing a simple type (e.g. `type[T]`) directly via `arg` and `result` is for convenience, and is equivalent to passing a one-element tuple of the same simple type (i.e. `type[tuple[T]]`) via `args` and `resultset`.

The number of types in `args` must correspond to the number of query parameters. (This is validated on calling `sql(...)` for the *t-string* syntax.) The number of types in `resultset` must correspond to the number of columns returned by the query.

Both `args` and `resultset` types must be compatible with their corresponding PostgreSQL query parameter types and resultset column types, respectively. The following table shows the mapping between PostgreSQL and Python types.

| PostgreSQL type   | Python type        |
| ----------------- | ------------------ |
| `bool`            | `bool`             |
| `smallint`        | `int`              |
| `integer`         | `int`              |
| `bigint`          | `int`              |
| `real`/`float4`   | `float`            |
| `double`/`float8` | `float`            |
| `decimal`         | `Decimal`          |
| `numeric`         | `Decimal`          |
| `date`            | `date`             |
| `time`            | `time` (naive)     |
| `timetz`          | `time` (tz)        |
| `timestamp`       | `datetime` (naive) |
| `timestamptz`     | `datetime` (tz)    |
| `char(N)`         | `str`              |
| `varchar(N)`      | `str`              |
| `text`            | `str`              |
| `bytea`           | `bytes`            |
| `json`            | `str`              |
| `jsonb`           | `str`              |
| `uuid`            | `UUID`             |
| enumeration       | `E: StrEnum`          |

### Using a SQL object

The function `sql` returns an object that derives from the base class `_SQL` and is specific to the number and types of parameters passed in `args` and `resultset`.

The following functions are available on SQL objects:

```python
async def execute(self, connection: Connection, *args: *P) -> None: ...
async def executemany(self, connection: Connection, args: Iterable[tuple[*P]]) -> None: ...
async def fetch(self, connection: Connection, *args: *P) -> list[tuple[*R]]: ...
async def fetchmany(self, connection: Connection, args: Iterable[tuple[*P]]) -> list[tuple[*R]]: ...
async def fetchrow(self, connection: Connection, *args: *P) -> tuple[*R] | None: ...
async def fetchval(self, connection: Connection, *args: *P) -> R1: ...
```

`Connection` may be an `asyncpg.Connection` or an `asyncpg.pool.PoolConnectionProxy` acquired from a connection pool.

`*P` and `*R` denote several types (a type pack) corresponding to those listed in `args` and `resultset`, respectively.

Only those functions are prompted on code completion that make sense in the context of the given number of input and output arguments. Specifically, `fetchval` is available only for a single type passed to `resultset`, and `executemany` and `fetchmany` are available only if the query takes (one or more) parameters.


## Run-time behavior

When a call such as `sql.executemany(conn, records)` or `sql.fetch(conn, param1, param2)` is made on a `SQL` object at run time, the library invokes `connection.prepare(sql)` to create a `PreparedStatement` and compares the actual statement signature against the expected Python types. Unfortunately, PostgreSQL doesn't propagate nullability via prepared statements: resultset types that are declared as required (e.g. `T` as opposed to `T | None`) are validated at run time.
