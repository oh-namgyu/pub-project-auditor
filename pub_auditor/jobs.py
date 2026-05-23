"""In-memory job queue for async audit runs.

The web dashboard fires POST /api/audit, gets back a job_id immediately, then
listens on /api/audit/events/{id} (Server-Sent Events) for progress. The
worker spawns the claude subprocess per task; if the user hits the cancel
button, DELETE /api/audit/{id} sends SIGTERM and the job's state flips
to ``cancelled``.

A single Python process owns the store — no database, no cross-process
coordination. ``max_concurrent`` caps the number of active jobs (queued
or running). Past the cap, ``create()`` raises and the HTTP layer
translates that to 429.
"""
from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional  # noqa: F401


@dataclass
class TaskRecord:
    task: str
    status: str = "pending"  # pending → running → done | failed | cancelled
    outcome: Optional[dict] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None


@dataclass
class Job:
    id: str
    project: str
    tasks: list[TaskRecord]
    status: str = "queued"  # queued → running → done | failed | cancelled
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    error: Optional[str] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    proc: Any = None  # subprocess.Popen, set while a task is running
    listeners: list[asyncio.Queue] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "project": self.project,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "error": self.error,
            "tasks": [
                {
                    "task": t.task, "status": t.status,
                    "started_at": t.started_at, "ended_at": t.ended_at,
                    "outcome": t.outcome,
                } for t in self.tasks
            ],
        }


class JobStore:
    def __init__(self, max_concurrent: int = 2, ttl_seconds: int = 24 * 3600):
        self._jobs: dict[str, Job] = {}
        self._max_concurrent = max_concurrent
        self._ttl_seconds = ttl_seconds
        # Lazily created so JobStore can be instantiated outside a running
        # event loop (e.g. in tests that drive it synchronously).
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return list(self._jobs.values())

    def active_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status in ("queued", "running"))

    def _is_expired(self, job: Job, now: float) -> bool:
        if job.status in ("queued", "running"):
            return False
        anchor = job.ended_at or job.created_at
        return (now - anchor) > self._ttl_seconds

    def sweep(self) -> int:
        """Drop terminal jobs older than ttl_seconds. Returns count removed.
        Called lazily by list() / create() so we never need a background task."""
        now = time.time()
        expired = [jid for jid, j in self._jobs.items() if self._is_expired(j, now)]
        for jid in expired:
            del self._jobs[jid]
        return len(expired)

    async def create(self, project: str, tasks: list[str]) -> Job:
        async with self._get_lock():
            # Drop expired jobs first so a creator who's been idle for a day
            # doesn't see ghost entries against the concurrency cap.
            self.sweep()
            if self.active_count() >= self._max_concurrent:
                raise RuntimeError(
                    f"max concurrent jobs reached ({self._max_concurrent}); "
                    "wait for an existing job to finish or cancel one"
                )
            job_id = secrets.token_urlsafe(8)
            job = Job(id=job_id, project=project,
                      tasks=[TaskRecord(task=t) for t in tasks])
            self._jobs[job_id] = job
            return job

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status not in ("queued", "running"):
            return False
        job.cancel_event.set()
        if job.proc is not None:
            try:
                job.proc.terminate()
            except Exception:
                pass
        return True

    async def broadcast(self, job: Job, event: dict) -> None:
        for q in list(job.listeners):
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def subscribe(self, job: Job) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        job.listeners.append(q)
        return q

    def unsubscribe(self, job: Job, q: asyncio.Queue) -> None:
        if q in job.listeners:
            job.listeners.remove(q)
