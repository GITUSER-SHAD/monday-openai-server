"""DuckDB access layer. Re-runnable: every stage is idempotent."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from .config import DEFAULT_DB, PKG_ROOT

SCHEMA_PATH = PKG_ROOT / "schema.sql"


def connect(db_path: Path | str = DEFAULT_DB, read_only: bool = False):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA_PATH.read_text())
    return con


def new_run_id() -> str:
    return f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


def log(con, run_id: str, stage: str, level: str, message: str) -> None:
    """Append to run_log and echo, so data-quality notes end up in the DB too."""
    con.execute(
        "INSERT INTO run_log (run_id, stage, ts, level, message) VALUES (?,?,?,?,?)",
        [run_id, stage, datetime.now(timezone.utc), level, message],
    )
    print(f"[{stage}] {level}: {message}", flush=True)


def replace_table(con, table: str, df: pd.DataFrame) -> int:
    """Idempotent full replace of a table's rows, preserving the declared schema."""
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    if df is None or df.empty:
        con.execute(f"DELETE FROM {table}")
        return 0
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            out[col] = None
    out = out[cols]
    con.execute(f"DELETE FROM {table}")
    con.register("_staging", out)
    con.execute(f"INSERT INTO {table} SELECT * FROM _staging")
    con.unregister("_staging")
    return len(out)


def upsert_prices(con, df: pd.DataFrame) -> int:
    """Insert price rows, ignoring (ticker, date) pairs already stored."""
    if df is None or df.empty:
        return 0
    cols = [r[0] for r in con.execute("DESCRIBE prices").fetchall()]
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            out[col] = None
    out = out[cols].drop_duplicates(subset=["ticker", "date"])
    con.register("_price_staging", out)
    con.execute(
        """
        INSERT INTO prices
        SELECT s.* FROM _price_staging s
        WHERE NOT EXISTS (
            SELECT 1 FROM prices p WHERE p.ticker = s.ticker AND p.date = s.date
        )
        """
    )
    con.unregister("_price_staging")
    return len(out)


def table_count(con, table: str) -> int:
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
