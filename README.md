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

# create a list of data-class instances from a list of typed tuples
@dataclass
class DataObject:
    boolean_value: bool
    integer_value: int
    string_value: str | None

# ✅ Valid initializer call
items = [DataObject(*row) for row in rows]

@dataclass
class MismatchedObject:
    boolean_value: bool
    integer_value: int
    string_value: str

# ⚠️ Argument of type "int | None" cannot be assigned to parameter "integer_value" of type "int" in function "__init__"; "None" is not assignable to "int"
items = [MismatchedObject(*row) for row in rows]
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

#### Parameters to factory function

The parameter `stmt` represents a SQL expression, either as a literal string or a template (i.e. a *t-string*).

If the expression is a string, it can have PostgreSQL parameter placeholders such as `$1`, `$2` or `$3`:

```python
"INSERT INTO table_name (col_1, col_2, col_3) VALUES ($1, $2, $3);"
```

If the expression is a *t-string*, it can have replacement fields that evaluate to integers:

```python
t"INSERT INTO table_name (col_1, col_2, col_3) VALUES ({1}, {2}, {3});"
```

The parameters `args` and `resultset` take a `tuple` of several types `Px` or `Rx`.

The parameters `arg` and `result` take a single type `P` or `R`. Passing a simple type (e.g. `type[T]`) directly via `arg` and `result` is for convenience, and is equivalent to passing a one-element tuple of the same simple type (i.e. `type[tuple[T]]`) via `args` and `resultset`.

The number of types in `args` must correspond to the number of query parameters. (This is validated on calling `sql(...)` for the *t-string* syntax.) The number of types in `resultset` must correspond to the number of columns returned by the query.

#### Argument and resultset types

When passing Python types via the parameters `args` and `resultset`, each type may be any of the following:

* (required) simple type
* optional simple type (`T | None`)
* special union type

Simple types include:

* `bool`
* `int`
* `float`
* `decimal.Decimal`
* `datetime.date`
* `datetime.time`
* `datetime.datetime`
* `datetime.timedelta`
* `str`
* `bytes`
* `uuid.UUID`
* `IPv4Address`
* `IPv6Address`
* `IPv4Network`
* `IPv6Network`
* a user-defined class that derives from `StrEnum`

Special union types are as follows:

* `JsonType` to represent an object reconstructed from a JSON string
* `IPv4Address | IPv6Address` to denote either an IPv4 or IPv6 address
* `IPv4Network | IPv6Network` to denote either an IPv4 or IPv6 network definition

Types are grouped together with `tuple`:

```python
tuple[bool, int, str | None]
```

Both `args` and `resultset` types must be compatible with their corresponding PostgreSQL query parameter types and resultset column types, respectively. The following table shows the mapping between PostgreSQL and Python types. When there are multiple options separated by a slash, either of the types can be specified as a source or target type.

| PostgreSQL type              | Python type                  |
| ---------------------------- | ---------------------------- |
| `bool`                       | `bool`                       |
| `smallint`                   | `int`                        |
| `integer`                    | `int`                        |
| `bigint`                     | `int`                        |
| `real`/`float4`              | `float`                      |
| `double`/`float8`            | `float`                      |
| `decimal`/`numeric`          | `Decimal`                    |
| `date`                       | `date`                       |
| `time`                       | `time` (naive)               |
| `timetz`                     | `time` (tz)                  |
| `timestamp`                  | `datetime` (naive)           |
| `timestamptz`                | `datetime` (tz)              |
| `interval`                   | `timedelta`                  |
| `char(N)`                    | `str`                        |
| `varchar(N)`                 | `str`                        |
| `text`                       | `str`                        |
| `bytea`                      | `bytes`                      |
| `uuid`                       | `UUID`                       |
| `cidr`                       | `IPvXNetwork`                |
| `inet`                       | `IPvXNetwork`/`IPvXAddress`  |
| `macaddr`                    | `str`                        |
| `macaddr8`                   | `str`                        |
| `json`                       | `str`/`JsonType`             |
| `jsonb`                      | `str`/`JsonType`             |
| `xml`                        | `str`                        |
| enumeration                  | `E: StrEnum`                 |

PostgreSQL types `json` and `jsonb` are [returned by asyncpg](https://magicstack.github.io/asyncpg/current/usage.html#type-conversion) as Python type `str`. However, if we specify the union type `JsonType` in `args` or `resultset`, the JSON string is parsed as if by calling `json.loads()`. If the library `orjson` is present, its faster routines are invoked instead of the slower standard library implementation in the module `json`.

`JsonType` is defined in the module `asyncpg_typed` as follows:

```python
JsonType = None | bool | int | float | str | dict[str, "JsonType"] | list["JsonType"]
```

`IPvXNetwork` is a shorthand for either of the following:

* `IPv4Network`
* `IPv6Network`
* their union type `IPv4Network | IPv6Network`

`IPvXAddress` stands for either of the following:

* `IPv4Address`
* `IPv6Address`
* their union type `IPv4Address | IPv6Address`

#### SQL statement as an f-string

In addition to the `sql` function, SQL objects can be created with the functionally identical `unsafe_sql` function. As opposed to its safer alternative, the first parameter of `unsafe_sql` has the plain type `str`, allowing us to pass an f-string. This can prove useful if we want to inject the value of a Python variable at location where binding parameters are not permitted by PostgreSQL syntax, e.g. substitute the name of a database table to dynamically create a SQL statement.

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

When a call such as `sql.executemany(conn, records)` or `sql.fetch(conn, param1, param2)` is made on a `SQL` object at run time, the library invokes `connection.prepare(sql)` to create a `PreparedStatement` and compares the actual statement signature against the expected Python types. If the expected and actual signatures don't match, an exception `TypeMismatchError` (subclass of `TypeError`) is raised.

Unfortunately, PostgreSQL doesn't propagate nullability via prepared statements: resultset types that are declared as required (e.g. `T` as opposed to `T | None`) are validated at run time. When a `None` value is encountered for a required type, an exception `NoneTypeError` (subclass of `TypeError`) is raised.

PostgreSQL doesn't differentiate between IPv4 and IPv6 network definitions, or IPv4 and IPv6 addresses in the types `cidr` and `inet`. This means that semantically a union type is returned. If you specify a more restrictive type, the resultset data is validated dynamically at run time.
