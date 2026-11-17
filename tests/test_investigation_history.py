import json
from datetime import datetime

from app import main
from app.db import connect
from app.seed import initialize_database


def test_investigation_history_lists_recent_runs_and_keeps_detail_route(tmp_path, monkeypatch):
    database = tmp_path / "history.duckdb"
    initialize_database(str(database))
    monkeypatch.setenv("BI_AGENT_DB", str(database))
    monkeypatch.setattr(main, "cloud_mode", lambda: False)
    older_id = "older-run"
    newer_id = "newer-run"
    older_result = {"current_start": "2026-10-01", "current_end": "2026-10-07", "findings": []}
    newer_result = {
        "current_start": "2026-10-08",
        "current_end": "2026-10-14",
        "findings": [{"id": "revenue"}],
    }

    with connect(database) as connection:
        connection.execute(
            "INSERT INTO investigations VALUES (?, ?, ?, ?), (?, ?, ?, ?)",
            [
                older_id, datetime(2026, 10, 8), 7, json.dumps(older_result),
                newer_id, datetime(2026, 10, 15), 7, json.dumps(newer_result),
            ],
        )

    history = main.list_investigations(limit=1, tenant=None)

    assert history["investigations"] == [
        {
            "investigation_id": newer_id,
            "run_at": "2026-10-15T00:00:00",
            "window_days": 7,
            "current_start": "2026-10-08",
            "current_end": "2026-10-14",
            "finding_count": 1,
        }
    ]
    assert main.get_investigation(newer_id, tenant=None)["findings"] == [{"id": "revenue"}]
