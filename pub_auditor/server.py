"""FastAPI dashboard. Run with: python -m pub_auditor.server"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pub_auditor import scanner
from pub_auditor.config import Config, ConfigError, load
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


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="pub-project-auditor", version="0.1.0")
    web_dir = cfg.project_root / "pub_auditor" / "web"

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/targets")
    def list_targets() -> dict:
        if not cfg.targets_path.is_file():
            scanner.write_targets(cfg, scanner.scan(cfg))
        return json.loads(cfg.targets_path.read_text())

    @app.post("/api/rescan")
    def rescan() -> dict:
        path = scanner.write_targets(cfg, scanner.scan(cfg))
        return {"ok": True, "path": str(path)}

    @app.post("/api/targets/toggle")
    def toggle(req: ToggleRequest) -> dict:
        return {"updated": scanner.set_enabled_bulk(cfg, req.updates)}

    @app.post("/api/audit")
    async def trigger_audit(req: AuditRequest) -> dict:
        unknown = [t for t in req.tasks if t not in TASK_MAP]
        if unknown:
            raise HTTPException(400, f"unknown tasks: {unknown}")
        if not cfg.targets_path.is_file():
            scanner.write_targets(cfg, scanner.scan(cfg))
        data = json.loads(cfg.targets_path.read_text())
        target = next((t for t in data["targets"] if t["name"] == req.project), None)
        if not target:
            raise HTTPException(404, f"project not found: {req.project}")
        if not target.get("enabled", True):
            raise HTTPException(403, f"project is disabled: {req.project}")
        project_path = Path(target["path"])
        results = []
        for task in req.tasks:
            fn = TASK_MAP[task]
            outcome = await asyncio.to_thread(fn, cfg, project_path, req.project)
            results.append({"task": task, **outcome})
        return {"project": req.project, "results": results}

    @app.get("/api/reports")
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

    @app.get("/api/report")
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
