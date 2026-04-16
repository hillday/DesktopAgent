from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional


@dataclass
class RunRecord:
    created_at: str
    task: str
    status: str
    provider: str
    model: str
    logs: List[str] = field(default_factory=list)


def history_path() -> Path:
    return Path(__file__).resolve().parent / "history.json"


def load_history(path: Optional[Path] = None) -> List[RunRecord]:
    path = path or history_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        records: List[RunRecord] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            records.append(
                RunRecord(
                    created_at=str(item.get("created_at", "")),
                    task=str(item.get("task", "")),
                    status=str(item.get("status", "unknown")),
                    provider=str(item.get("provider", "")),
                    model=str(item.get("model", "")),
                    logs=[str(x) for x in item.get("logs", []) if isinstance(x, str)],
                )
            )
        return records
    except Exception:
        return []


def save_history(records: List[RunRecord], path: Optional[Path] = None) -> None:
    path = path or history_path()
    raw = [asdict(r) for r in records[:50]]
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def append_history(record: RunRecord, path: Optional[Path] = None) -> List[RunRecord]:
    existing = load_history(path)
    existing.insert(0, record)
    existing = existing[:50]
    save_history(existing, path)
    return existing


def new_record(task: str, status: str, provider: str, model: str, logs: List[str]) -> RunRecord:
    return RunRecord(
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        task=task,
        status=status,
        provider=provider,
        model=model,
        logs=list(logs),
    )
