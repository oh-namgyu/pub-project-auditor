"""Append-only JSONL audit log with size-based rotation.

When AUDITOR_AUDIT_LOG_PATH is set, every job emits one line on completion
recording: timestamp, job id, project, tasks, status, started/ended,
per-task outcomes, total cost, error. Useful for billing audits, incident
forensics, or wiring into a downstream pipeline.

When the env var is unset, append() is a no-op so there's no perf hit.

Rotation: when the current file would exceed AUDITOR_AUDIT_LOG_MAX_BYTES
(default 10 MiB), it's renamed to <path>.1, the existing .1 → .2, etc.,
keeping at most AUDITOR_AUDIT_LOG_BACKUPS (default 5) historical files.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUPS = 5


def _rotate_if_needed(path: Path, max_bytes: int, backups: int) -> None:
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
    except OSError:
        return
    for i in range(backups, 0, -1):
        src = path.with_suffix(path.suffix + f".{i}")
        dst = path.with_suffix(path.suffix + f".{i + 1}")
        if not src.exists():
            continue
        try:
            if i == backups:
                src.unlink()
            else:
                src.rename(dst)
        except OSError:
            pass
    try:
        path.rename(path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass


def append(path: Optional[Path], record: dict[str, Any]) -> None:
    if path is None:
        return
    max_bytes = int(os.environ.get("AUDITOR_AUDIT_LOG_MAX_BYTES", DEFAULT_MAX_BYTES))
    backups = int(os.environ.get("AUDITOR_AUDIT_LOG_BACKUPS", DEFAULT_BACKUPS))
    record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(path, max_bytes, backups)
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
