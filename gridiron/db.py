"""
Thin SQLite access layer shared by ingestion, modeling, and the frontend.

Uses SQLAlchemy for clean ``pandas`` round-trips while keeping the engine
SQLite-local (zero-config, file-backed). Swap ``DB_URL`` in ``config`` for
Postgres later without touching call sites.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from gridiron import config

_engine: Engine | None = None


def get_engine() -> Engine:
    """Return a process-wide SQLAlchemy engine bound to the project DB."""
    global _engine
    if _engine is None:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(config.DB_URL, future=True)
    return _engine


def run_sql_script(path: str | Path) -> None:
    """Execute a multi-statement ``.sql`` file (e.g. the schema DDL)."""
    sql = Path(path).read_text()
    engine = get_engine()
    with engine.begin() as conn:
        for statement in _split_statements(sql):
            conn.execute(text(statement))


def _split_statements(sql: str) -> list[str]:
    """Split a SQL script into statements.

    Strips ``--`` line comments *before* splitting on ``;`` so semicolons inside
    comments (e.g. "USD; NULL otherwise") don't truncate a statement. Assumes no
    ``--`` appears inside a string literal, which holds for this project's DDL.
    """
    cleaned: list[str] = []
    for line in sql.splitlines():
        idx = line.find("--")
        if idx != -1:
            line = line[:idx]
        if line.strip():
            cleaned.append(line)
    joined = "\n".join(cleaned)
    return [stmt.strip() for stmt in joined.split(";") if stmt.strip()]


def write_table(df: pd.DataFrame, table: str, if_exists: str = "replace") -> int:
    """Persist a DataFrame to ``table``; returns the row count written."""
    df.to_sql(table, get_engine(), if_exists=if_exists, index=False)
    return len(df)


def read_table(table: str) -> pd.DataFrame:
    """Load an entire table into a DataFrame."""
    return pd.read_sql_table(table, get_engine())


def query(sql: str, **params) -> pd.DataFrame:
    """Run a parameterized SELECT and return the results as a DataFrame."""
    with get_engine().connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params or None)


def table_exists(table: str) -> bool:
    """True if ``table`` is present in the SQLite catalog."""
    sql = "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
    with get_engine().connect() as conn:
        return conn.execute(text(sql), {"t": table}).first() is not None
