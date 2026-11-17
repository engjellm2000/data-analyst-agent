from __future__ import annotations

from typing import Iterable


def score(scenarios: Iterable[dict], predictions: dict[str, dict]) -> dict:
    scenarios = list(scenarios)
    incidents = [item for item in scenarios if item["type"] not in {"control", "red_herring"}]
    controls = [item for item in scenarios if item["type"] in {"control", "red_herring"}]
    detected = [item for item in incidents if predictions.get(item["id"], {}).get("detected")]
    correct = [item for item in detected if predictions[item["id"]].get("root_cause") == item["root_cause"]]
    false_alarms = [item for item in controls if predictions.get(item["id"], {}).get("detected")]
    costs = [predictions.get(item["id"], {}).get("cost_usd", 0) for item in scenarios]
    return {"scenario_count": len(scenarios), "detection_rate": round(len(detected) / len(incidents), 3) if incidents else 0, "root_cause_accuracy": round(len(correct) / len(detected), 3) if detected else 0, "false_alarm_rate": round(len(false_alarms) / len(controls), 3) if controls else 0, "cost_per_investigation_usd": round(sum(costs) / len(costs), 4) if costs else 0}
