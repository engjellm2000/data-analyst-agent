"""Run analytics against deterministic incident and clean-control fixtures."""
from __future__ import annotations

import json
from pathlib import Path
from datetime import date, datetime, timezone
from tempfile import TemporaryDirectory

from app.analytics import investigate
from app.db import connect
from app.seed import initialize_database
from evals.scorers import score

ROOT = Path(__file__).resolve().parent


def run() -> dict:
    scenarios = [
        {"id": "known-returns-incident", "type": "returns", "root_cause": "Home"},
        {"id": "known-aov-incident", "type": "aov", "root_cause": "Paid search"},
        {"id": "clean-control", "type": "control", "root_cause": None},
    ]
    predictions = {}
    with TemporaryDirectory(prefix="bi-agent-eval-") as directory:
        for scenario in scenarios:
            is_control = scenario["type"] == "control"
            database = Path(directory) / f"{scenario['id']}.duckdb"
            initialize_database(
                str(database),
                end_date=date(2026, 10, 31),
                inject_incidents=not is_control,
            )
            with connect(database) as connection:
                result = investigate(
                    connection,
                    window_days=30,
                    as_of=date(2026, 10, 31),
                )
            if is_control:
                detected = any(item["id"] != "steady" for item in result["findings"])
                root_cause = None
            else:
                expected_id = "returns" if scenario["type"] == "returns" else "basket-value"
                finding = next((item for item in result["findings"] if item["id"] == expected_id), None)
                detected = finding is not None
                root_cause = finding["segment"] if finding else None
            predictions[scenario["id"]] = {
                "detected": detected,
                "root_cause": root_cause,
                "cost_usd": 0.0,
            }
    fixture_result = score(scenarios, predictions)
    fixture_result["dataset"] = "Deterministic synthetic incident and clean-control fixtures"
    fixture_result["claim"] = "Fixture behavior only; not a real-world performance estimate."
    catalog = json.loads((ROOT / "scenarios" / "scenarios.json").read_text(encoding="utf-8"))
    result = {
        "version": "v0.3-fixtures",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "fixture_benchmark": fixture_result,
        "contract_catalog": {
            "scenario_count": len(catalog),
            "status": "Catalog only; scenarios without individual data fixtures are not scored.",
        },
    }
    target = ROOT / "results" / "latest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
