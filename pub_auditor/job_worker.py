"""Audit job worker — the coroutine that drives one queued job to completion.

Extracted from server.py so the HTTP layer only assembles routes. The worker
runs each task in a thread, streams SSE events to subscribed listeners,
enforces the per-job cost cap, and propagates cancellation into the running
claude subprocess via the on_proc_start hook.
"""
from __future__ import annotations

import asyncio
import time
import traceback
from pathlib import Path

from pub_auditor import audit_log
from pub_auditor.config import Config
from pub_auditor.jobs import Job, JobStore
from pub_auditor.tasks import TASKS


async def run_job(cfg: Config, store: JobStore, job: Job, project_path: Path) -> None:
    """Worker coroutine for one job. Runs each task in a thread, emits SSE
    events to subscribed listeners, respects the cancel_event between tasks
    and propagates it into the running claude subprocess via on_proc_start.

    Enforces AUDITOR_COST_USD_MAX across the job: once accumulated cost
    exceeds the cap, remaining tasks are skipped with status=cancelled and
    job.error is set to a budget-overrun message."""
    job.status = "running"
    job.started_at = time.time()
    await store.broadcast(job, {"type": "job_started", **job.snapshot()})

    cost_so_far = 0.0

    try:
        for tr in job.tasks:
            if job.cancel_event.is_set():
                tr.status = "cancelled"
                continue
            if cfg.cost_usd_max is not None and cost_so_far >= cfg.cost_usd_max:
                tr.status = "cancelled"
                continue
            tr.status = "running"
            tr.started_at = time.time()
            await store.broadcast(job, {"type": "task_started", "task": tr.task, **job.snapshot()})

            fn = TASKS[tr.task]

            def on_proc_start(proc) -> None:
                job.proc = proc
                if job.cancel_event.is_set():
                    try:
                        from pub_auditor import runner
                        runner.terminate_proc(proc)
                    except Exception:
                        pass

            outcome = await asyncio.to_thread(fn, cfg, project_path, job.project, on_proc_start)
            job.proc = None
            tr.outcome = dict(outcome)
            tr.ended_at = time.time()
            cost = outcome.get("cost_usd") if isinstance(outcome, dict) else None
            cost_so_far += float(cost or 0.0)
            if outcome.get("success"):
                tr.status = "done"
            elif outcome.get("error") == "cancelled":
                tr.status = "cancelled"
            else:
                tr.status = "failed"
            await store.broadcast(job, {"type": "task_done", "task": tr.task,
                                        "cost_so_far_usd": cost_so_far, **job.snapshot()})

        if cfg.cost_usd_max is not None and cost_so_far >= cfg.cost_usd_max and \
                any(t.status == "cancelled" for t in job.tasks):
            job.status = "cancelled"
            job.error = (f"cost cap reached: ${cost_so_far:.2f} >= ${cfg.cost_usd_max:.2f} "
                         "(AUDITOR_COST_USD_MAX)")
        elif job.cancel_event.is_set() and any(t.status == "cancelled" for t in job.tasks):
            job.status = "cancelled"
        elif all(t.status == "done" for t in job.tasks):
            job.status = "done"
        elif any(t.status == "failed" for t in job.tasks):
            job.status = "failed"
            job.error = "one or more tasks failed; see per-task outcome"
        else:
            job.status = "cancelled"
    except Exception as e:
        traceback.print_exc()                 # broad catch — print the traceback to stderr so a real bug isn't swallowed as 'unexpected'
        job.status = "failed"
        job.error = f"unexpected: {e}"
    finally:
        job.ended_at = time.time()
        await store.broadcast(job, {"type": "job_ended", **job.snapshot()})
        # Persistent audit trail — no-op if AUDITOR_AUDIT_LOG_PATH unset.
        try:
            audit_log.append(cfg.audit_log_path, audit_log.for_job(job, cost_usd=cost_so_far))
        except Exception:
            pass
        # Signal end-of-stream so SSE listeners can close cleanly.
        await store.broadcast(job, {"type": "__close__"})
