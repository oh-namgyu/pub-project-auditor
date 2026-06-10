"""FastAPI dashboard. Run with: python -m pub_auditor.server"""
from __future__ import annotations

import asyncio
import hmac
import json
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pub_auditor import scanner
from pub_auditor.config import Config, ConfigError, load
from pub_auditor.job_worker import run_job
from pub_auditor.jobs import Job, JobStore
from pub_auditor.masking import (
    _MASK,
    mask_job_snapshot,
    mask_targets_response,
)
from pub_auditor.tasks import TASKS

# Back-compat re-exports: external callers / tests have historically reached
# these via `pub_auditor.server.<name>`. Keep the symbol paths stable after the
# job-worker and path-masking logic moved into dedicated modules.
_run_job = run_job
_mask_job_snapshot = mask_job_snapshot
_mask_targets_response = mask_targets_response


class AuditRequest(BaseModel):
    project: str
    tasks: list[str]


class ToggleRequest(BaseModel):
    updates: dict[str, bool]


def _check_token(cfg: Config, request: Request, allow_query: bool = False) -> None:
    """Compare AUDITOR_TOKEN against request token using constant-time compare.

    Reads `Authorization: Bearer <token>`. The `?token=<token>` query fallback
    is only honored when `allow_query=True` (the SSE endpoint, since EventSource
    can't set headers) — for every other route we require the header so the
    secret doesn't end up in access logs / referrers. When `cfg.auth_token` is
    None (loopback-only deploy) the gate is a no-op.
    """
    if cfg.auth_token is None:
        return
    auth = request.headers.get("authorization", "")
    presented = auth.removeprefix("Bearer ").strip() if auth.lower().startswith("bearer ") else ""
    if not presented and allow_query:
        presented = request.query_params.get("token", "")
    if not presented or not hmac.compare_digest(presented, cfg.auth_token):
        raise HTTPException(status_code=401, detail="invalid or missing token")


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="pub-project-auditor", version="0.1.0")
    web_dir = cfg.project_root / "pub_auditor" / "web"
    store = JobStore(max_concurrent=cfg.max_concurrent, ttl_seconds=cfg.job_ttl_seconds)
    app.state.job_store = store

    def auth(request: Request) -> None:
        _check_token(cfg, request)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "active_jobs": store.active_count(),
                "max_concurrent": cfg.max_concurrent}

    @app.get("/api/targets", dependencies=[Depends(auth)])
    def list_targets() -> dict:
        try:
            data = scanner.load_targets(cfg)
        except scanner.TargetsError:
            # Corrupt on disk — rebuild from a fresh scan rather than 500.
            scanner.write_targets(cfg, scanner.scan(cfg))
            data = scanner.load_targets(cfg)
        if cfg.mask_paths:
            data = mask_targets_response(data)
        return data

    @app.post("/api/rescan", dependencies=[Depends(auth)])
    def rescan() -> dict:
        path = scanner.write_targets(cfg, scanner.scan(cfg))
        # Absolute path leaks the operator's layout — mask when enabled.
        return {"ok": True, "path": _MASK if cfg.mask_paths else str(path)}

    @app.post("/api/targets/toggle", dependencies=[Depends(auth)])
    def toggle(req: ToggleRequest) -> dict:
        return {"updated": scanner.set_enabled_bulk(cfg, req.updates)}

    @app.post("/api/audit", dependencies=[Depends(auth)])
    async def trigger_audit(req: AuditRequest) -> dict:
        """Enqueue an audit job. Returns 202 + job_id; subscribe to
        /api/audit/events/{id} for progress, DELETE /api/audit/{id} to cancel."""
        unknown = [t for t in req.tasks if t not in TASKS]
        if unknown:
            raise HTTPException(400, f"unknown tasks: {unknown}")
        if not req.tasks:
            raise HTTPException(400, "tasks must be non-empty")
        try:
            target = scanner.find_target(cfg, req.project)
        except scanner.TargetsError as e:
            raise HTTPException(500, f"targets.json unreadable: {e}") from e
        if not target:
            raise HTTPException(404, f"project not found: {req.project}")
        if not target.get("enabled", True):
            raise HTTPException(403, f"project is disabled: {req.project}")

        project_path = Path(target["path"])
        try:
            job = await store.create(req.project, req.tasks)
        except RuntimeError as e:
            raise HTTPException(429, str(e)) from e

        asyncio.create_task(run_job(cfg, store, job, project_path))
        return {"job_id": job.id, "project": req.project, "tasks": req.tasks,
                "status": job.status}

    def _snap(job: Job) -> dict:
        snap = job.snapshot()
        return mask_job_snapshot(snap) if cfg.mask_paths else snap

    @app.get("/api/audit/{job_id}", dependencies=[Depends(auth)])
    def get_job(job_id: str) -> dict:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return _snap(job)

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
        _check_token(cfg, request, allow_query=True)
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")

        def _emit(payload: dict) -> str:
            if cfg.mask_paths:
                payload = mask_job_snapshot(payload)
            return f"data: {json.dumps(payload)}\n\n"

        async def gen():
            q = store.subscribe(job)
            try:
                # Initial snapshot so a late subscriber sees current state.
                yield _emit({"type": "snapshot", **job.snapshot()})
                # If the job already reached a terminal state before this
                # subscriber connected, there will be no further events (the
                # __close__ was already broadcast). Close now instead of
                # holding the stream open forever.
                if job.status in ("done", "failed", "cancelled"):
                    return
                while True:
                    try:
                        event = await asyncio.wait_for(q.get(), timeout=25.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if event.get("type") == "__close__":
                        break
                    yield _emit(event)
            finally:
                store.unsubscribe(job, q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no",
                                          "Cache-Control": "no-cache"})

    @app.get("/api/audits", dependencies=[Depends(auth)])
    def list_jobs(limit: int = 50, offset: int = 0) -> dict:
        """Paginated job list. Newest first. Limit clamped to [1, 200]."""
        store.sweep()
        limit = max(1, min(200, limit))
        offset = max(0, offset)
        all_sorted = sorted(store.all(), key=lambda j: -j.created_at)
        page = all_sorted[offset : offset + limit]
        return {
            "jobs": [_snap(j) for j in page],
            "total": len(all_sorted),
            "limit": limit,
            "offset": offset,
            "ttl_seconds": cfg.job_ttl_seconds,
        }

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
