"""Structured evidence log: it is intentionally serializable and visible to users."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scratchpad:
    entries: list[dict] = field(default_factory=list)

    def add(self, step: str, status: str, detail: str, **metadata: object) -> None:
        self.entries.append({"step": step, "status": status, "detail": detail, **metadata})

    def tested(self, hypothesis: str) -> bool:
        return any(item.get("hypothesis") == hypothesis for item in self.entries)
