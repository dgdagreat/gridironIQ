"""Read-only access layer the scouting agent exposes to Claude as `run_sql`.

Two responsibilities:
  1. Describe the warehouse schema (so Claude writes correct SQL).
  2. Execute a single read-only SELECT, safely, and return tidy rows.

The DuckDB connection is opened read-only; on top of that we allow only a single
SELECT/WITH statement and deny a keyword list, so a hallucinated `DROP` or an
`ATTACH` to some other file can never run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

WAREHOUSE_PATH = Path(__file__).resolve().parents[2] / "data" / "warehouse.duckdb"

# Schemas the agent may read. `main` = dbt marts/staging; `raw` = landed sources.
READABLE_SCHEMAS = ("main", "raw")

MAX_ROWS = 200          # rows returned to the model per query
MAX_CELL_CHARS = 200    # truncate very wide cell values

# Statements must start with one of these (after stripping comments/whitespace).
_ALLOWED_PREFIX = re.compile(r"^\s*(with|select)\b", re.IGNORECASE)
# Defense in depth on top of the read-only connection.
_DENY = re.compile(
    r"\b(attach|detach|copy|install|load|pragma|export|import|create|insert|"
    r"update|delete|drop|alter|call|set)\b",
    re.IGNORECASE,
)


class SqlNotAllowed(ValueError):
    """Raised when a query fails the read-only guard."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_markdown(self) -> str:
        if self.error:
            return f"ERROR: {self.error}"
        if not self.rows:
            return "(0 rows)"
        head = "| " + " | ".join(self.columns) + " |"
        sep = "| " + " | ".join("---" for _ in self.columns) + " |"
        body = [
            "| " + " | ".join(_fmt(c) for c in row) + " |" for row in self.rows
        ]
        note = f"\n\n_{self.row_count} rows"
        note += f" (truncated to first {MAX_ROWS})_" if self.truncated else " returned_"
        return "\n".join([head, sep, *body]) + note


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    s = str(v)
    if len(s) > MAX_CELL_CHARS:
        s = s[: MAX_CELL_CHARS - 1] + "…"
    return s.replace("|", "\\|").replace("\n", " ")


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql.strip().rstrip(";").strip()


def guard_sql(sql: str) -> str:
    """Return the cleaned SQL if it is a single read-only SELECT, else raise."""
    cleaned = _strip_sql_comments(sql)
    if not cleaned:
        raise SqlNotAllowed("empty query")
    if ";" in cleaned:
        raise SqlNotAllowed("only a single statement is allowed")
    if not _ALLOWED_PREFIX.match(cleaned):
        raise SqlNotAllowed("only SELECT / WITH queries are allowed")
    hit = _DENY.search(cleaned)
    if hit:
        raise SqlNotAllowed(f"keyword '{hit.group(0)}' is not allowed (read-only)")
    return cleaned


def run_sql(sql: str, warehouse: Path = WAREHOUSE_PATH) -> QueryResult:
    """Execute a guarded read-only query against the DuckDB warehouse."""
    try:
        cleaned = guard_sql(sql)
    except SqlNotAllowed as e:
        return QueryResult([], [], 0, error=str(e))

    try:
        con = duckdb.connect(str(warehouse), read_only=True)
    except Exception as e:  # noqa: BLE001 - warehouse missing / locked; surface as an error result
        return QueryResult([], [], 0, error=f"cannot open warehouse: {e}")
    try:
        cur = con.execute(f"SELECT * FROM ({cleaned}) AS _q LIMIT {MAX_ROWS + 1}")
        columns = [d[0] for d in cur.description]
        fetched = cur.fetchall()
    except Exception as e:  # noqa: BLE001 - any query error becomes a tool error for the model
        return QueryResult([], [], 0, error=f"query failed: {e}")
    finally:
        con.close()

    truncated = len(fetched) > MAX_ROWS
    rows = [list(r) for r in fetched[:MAX_ROWS]]
    return QueryResult(columns, rows, len(rows), truncated=truncated)


def schema_text(warehouse: Path = WAREHOUSE_PATH) -> str:
    """Compact table/column listing for the readable schemas, for the prompt."""
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        placeholders = ",".join("?" for _ in READABLE_SCHEMAS)
        rows = con.execute(
            f"""
            SELECT table_schema, table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema IN ({placeholders})
            ORDER BY table_schema, table_name, ordinal_position
            """,
            list(READABLE_SCHEMAS),
        ).fetchall()
    finally:
        con.close()

    by_table: dict[str, list[str]] = {}
    for schema, table, col, dtype in rows:
        by_table.setdefault(f"{schema}.{table}", []).append(f"{col} {dtype}")

    lines = []
    for table, cols in by_table.items():
        lines.append(f"{table}(" + ", ".join(cols) + ")")
    return "\n".join(lines)
