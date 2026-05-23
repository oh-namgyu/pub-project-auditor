"""FastAPI dashboard. Run with: python -m pub_auditor.server"""
from __future__ import annotations

import asyncio
import hmac
import json
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pub_auditor import audit_log, scanner
from pub_auditor.config import Config, ConfigError, load
from pub_auditor.jobs import Job, JobStore
from pub_auditor.tasks import review, security

TASK_MAP = {
    "review": review.run_review,
    "security": security.run_security,
}


class AuditRequest(BaseModel):
    project: str
    tasks: list[str]


class ToggleRequest(BaseModel):
    updates: dict[str, bool]


async def _run_job(cfg: Config, store: JobStore, job: Job, project_path: Path) -> None:
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

            fn = TASK_MAP[tr.task]

            def on_proc_start(proc) -> None:
                job.proc = proc
                if job.cancel_event.is_set():
                    try:
                        proc.terminate()
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


def _check_token(cfg: Config, request: Request) -> None:
    """Compare AUDITOR_TOKEN against request token using constant-time compare.

    Accepts either `Authorization: Bearer <token>` or `?token=<token>`. When
    `cfg.auth_token` is None (loopback-only deploy) the gate is a no-op.
    """
    if cfg.auth_token is None:
        return
    auth = request.headers.get("authorization", "")
    presented = auth.removeprefix("Bearer ").strip() if auth.lower().startswith("bearer ") else ""
    if not presented:
        presented = request.query_params.get("token", "")
    if not presented or not hmac.compare_digest(presented, cfg.auth_token):
        raise HTTPException(status_code=401, detail="invalid or missing token")


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="pub-project-auditor", version="0.1.0")
    web_dir = cfg.project_root / "pub_auditor" / "web"
    store = JobStore(max_concurrent=cfg.max_concurrent)
    app.state.job_store = store

    def auth(request: Request) -> None:
        _check_token(cfg, request)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "active_jobs": store.active_count(),
                "max_concurrent": cfg.max_concurrent}

    @app.get("/api/targets", dependencies=[Depends(auth)])
    def list_targets() -> dict:
        if not cfg.targets_path.is_file():
            scanner.write_targets(cfg, scanner.scan(cfg))
        return json.loads(cfg.targets_path.read_text())

    @app.post("/api/rescan", dependencies=[Depends(auth)])
    def rescan() -> dict:
        path = scanner.write_targets(cfg, scanner.scan(cfg))
        return {"ok": True, "path": str(path)}

    @app.post("/api/targets/toggle", dependencies=[Depends(auth)])
    def toggle(req: ToggleRequest) -> dict:
        return {"updated": scanner.set_enabled_bulk(cfg, req.updates)}

    @app.post("/api/audit", dependencies=[Depends(auth)])
    async def trigger_audit(req: AuditRequest) -> dict:
        """Enqueue an audit job. Returns 202 + job_id; subscribe to
        /api/audit/events/{id} for progress, DELETE /api/audit/{id} to cancel."""
        unknown = [t for t in req.tasks if t not in TASK_MAP]
        if unknown:
            raise HTTPException(400, f"unknown tasks: {unknown}")
        if not req.tasks:
            raise HTTPException(400, "tasks must be non-empty")
        if not cfg.targets_path.is_file():
            scanner.write_targets(cfg, scanner.scan(cfg))
        data = json.loads(cfg.targets_path.read_text())
        target = next((t for t in data["targets"] if t["name"] == req.project), None)
        if not target:
            raise HTTPException(404, f"project not found: {req.project}")
        if not target.get("enabled", True):
            raise HTTPException(403, f"project is disabled: {req.project}")

        project_path = Path(target["path"])
        try:
            job = await store.create(req.project, req.tasks)
        except RuntimeError as e:
            raise HTTPException(429, str(e))

        asyncio.create_task(_run_job(cfg, store, job, project_path))
        return {"job_id": job.id, "project": req.project, "tasks": req.tasks,
                "status": job.status}

    @app.get("/api/audit/{job_id}", dependencies=[Depends(auth)])
    def get_job(job_id: str) -> dict:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return job.snapshot()

    @app.delete("/api/audit/{job_id}", dependencies=[Depends(auth)])
    def cancel_job(job_id: str) -> dict:
        if not store.cancel(job_id):
            raise HTTPException(404, "job not found or already finished")
        return {"ok": True, "job_id": job_id, "status": "cancelling"}

    @app.get("/api/audit/{job_id}/events")
    async def job_events(job_id: str, request: Request, token: str = "") -> StreamingResponse:
        """SSE stream of job events. Token comes from ?token= query string
        rather than Authorization header because EventSource API can't set
        headers. Same constant-time compare as the rest of the gate."""
        _check_token(cfg, request)
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")

        async def gen():
            q = store.subscribe(job)
            try:
                # Initial snapshot so a late subscriber sees current state.
                yield f"data: {json.dumps({'type': 'snapshot', **job.snapshot()})}\n\n"
                while True:
                    try:
                        event = await asyncio.wait_for(q.get(), timeout=25.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if event.get("type") == "__close__":
                        break
                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                store.unsubscribe(job, q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no",
                                          "Cache-Control": "no-cache"})

    @app.get("/api/audits", dependencies=[Depends(auth)])
    def list_jobs() -> dict:
        return {"jobs": [j.snapshot() for j in sorted(store.all(),
                                                       key=lambda j: -j.created_at)]}

    @app.get("/api/reports", dependencies=[Depends(auth)])
    def list_reports() -> dict:
        if not cfg.reports_dir.is_dir():
            return {"projects": {}}
        result: dict[str, list[str]] = {}
        for proj_dir in sorted(cfg.reports_dir.iterdir()):
            if proj_dir.is_dir():
                files = sorted([f.name for f in proj_dir.iterdir() if f.suffix == ".md"], reverse=True)
                if files:
                    result[proj_dir.name] = files
        return {"projects": result}

    @app.get("/api/report", dependencies=[Depends(auth)])
    def get_report(project: str, file: str) -> FileResponse:
        path = (cfg.reports_dir / project / file).resolve()
        if not path.is_file() or cfg.reports_dir.resolve() not in path.parents:
            raise HTTPException(404, "report not found")
        return FileResponse(path, media_type="text/markdown")

    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app


def main() -> int:
    import uvicorn
    try:
        cfg = load()
    except ConfigError as e:
        print(f"[config] {e}")
        return 4
    app = create_app(cfg)
    print(f"[server] http://{cfg.host}:{cfg.port}  (repos: {cfg.repos_dir})")
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
