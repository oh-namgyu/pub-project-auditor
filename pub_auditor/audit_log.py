"""Append-only JSONL audit log.

When AUDITOR_AUDIT_LOG_PATH is set, every job emits one line on completion
recording: timestamp, job id, project, tasks, status, started/ended,
per-task outcomes, total cost, error. Useful for billing audits, incident
forensics, or wiring into a downstream pipeline.

When the env var is unset, append() is a no-op so there's no perf hit.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def append(path: Optional[Path], record: dict[str, Any]) -> None:
    if path is None:
        return
    record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def for_job(job, cost_usd: Optional[float] = None) -> dict[str, Any]:
    """Build a JSONL record from a Job snapshot. Pulled out so the server
    and tests can build the same shape without touching internals."""
    snap = job.snapshot() if hasattr(job, "snapshot") else dict(job)
    return {
        "job_id": snap["id"],
        "project": snap["project"],
        "status": snap["status"],
        "started_at": snap["started_at"],
        "ended_at": snap["ended_at"],
        "duration_seconds": (snap["ended_at"] - snap["started_at"])
                            if snap["started_at"] and snap["ended_at"] else None,
        "error": snap["error"],
        "cost_usd": cost_usd,
        "tasks": [
            {"task": t["task"], "status": t["status"],
             "cost_usd": (t.get("outcome") or {}).get("cost_usd") if t.get("outcome") else None}
            for t in snap["tasks"]
        ],
    }
