import csv
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterable

import duckdb
import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "business_intelligence.duckdb"


def database_path() -> Path:
    return Path(os.environ.get("BI_AGENT_DB", DEFAULT_DB_PATH)).expanduser().resolve()


class PostgresConnection:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def __enter__(self) -> "PostgresConnection":
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        return self._connection.__exit__(exc_type, exc_value, traceback)

    def execute(self, query: str, parameters: Any = None) -> Any:
        query = query.replace("?", "%s")
        return self._connection.execute(query, parameters)


def connect(
    path: str | Path | None = None,
    read_only: bool = False,
    *,
    user_id: str | None = None,
    tenant_id: str | None = None,
    jwt_claims: dict[str, Any] | None = None,
    privileged: bool = False,
) -> Any:
    database_url = os.environ.get("BI_AGENT_DATABASE_URL") if path is None else None
    if database_url:
        if read_only:
            raise ValueError("Use a read-only PostgreSQL database role for read-only access.")
        if not privileged and (not user_id or not tenant_id or not jwt_claims):
            raise PermissionError("Tenant-scoped PostgreSQL access requires a verified user and tenant.")
        raw_connection = psycopg.connect(database_url, row_factory=tuple_row)
        connection = PostgresConnection(raw_connection)
        try:
            if not privileged:
                claims_json = json.dumps(jwt_claims, separators=(",", ":"))
                connection.execute("SET LOCAL ROLE authenticated")
                connection.execute("SELECT set_config('request.jwt.claims', ?, true)", [claims_json])
                connection.execute("SELECT set_config('request.jwt.claim.sub', ?, true)", [user_id])
                connection.execute("SELECT set_config('request.jwt.claim.role', 'authenticated', true)")
                member = connection.execute(
                    "SELECT 1 FROM tenant_memberships WHERE user_id = ? AND tenant_id = ? LIMIT 1",
                    [user_id, tenant_id],
                ).fetchone()
                if member is None:
                    raise PermissionError("User is not a member of the requested tenant.")
            return connection
        except Exception:
            raw_connection.rollback()
            raw_connection.close()
            raise

    resolved = Path(path).expanduser().resolve() if path else database_path()
    if read_only and not resolved.exists():
        raise FileNotFoundError(f"Database does not exist: {resolved}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(resolved), read_only=read_only)


def copy_orders(connection: duckdb.DuckDBPyConnection, rows: Iterable[tuple]) -> None:
    """Bulk-load order tuples through DuckDB's native CSV reader."""
    with TemporaryDirectory(prefix="bi-agent-orders-") as directory:
        csv_path = Path(directory) / "orders.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerows(rows)
        connection.execute("COPY orders FROM ? (FORMAT CSV, NULL '')", [str(csv_path)])


def json_parameter(value: Any) -> Any:
    if isinstance(value, PostgresConnection):
        return Jsonb(value)
    return json.dumps(value)
