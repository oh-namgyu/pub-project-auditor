"""Job queue regression — SSE progress + cancel + concurrency cap.

Mocks the task runner so we don't need a real `claude` binary during CI.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def _isolated_env(monkeypatch):
    for k in ("AUDITOR_REPOS_DIR", "AUDITOR_HOST", "AUDITOR_TOKEN",
              "AUDITOR_PORT", "AUDITOR_OWNERS", "AUDITOR_MAX_CONCURRENT"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def _stub_task_map(monkeypatch, mock_outcome):
    """Replace TASKS entries so trigger_audit doesn't actually spawn claude."""
    from pub_auditor import server as srv

    def fake_review(cfg, project_path, project_name, on_proc_start=None):
        return dict(mock_outcome)

    def fake_security(cfg, project_path, project_name, on_proc_start=None):
        return dict(mock_outcome)

    monkeypatch.setitem(srv.TASKS, "review", fake_review)
    monkeypatch.setitem(srv.TASKS, "security", fake_security)


def _seed_targets(repos_dir: Path) -> None:
    """Make sure scanner finds at least one project so /api/audit accepts it."""
    (repos_dir / "demo").mkdir()


def _isolated_cfg(repos_dir: Path):
    """Load config and redirect targets_path / reports_dir to repos_dir so
    tests don't poison the real config/targets.json. Also mirror the
    pub_auditor/web/ directory so StaticFiles can mount it."""
    from dataclasses import replace

    from pub_auditor.config import load
    cfg = load()
    isolated_root = repos_dir / "_proj"
    isolated_root.mkdir(exist_ok=True)
    web_link = isolated_root / "pub_auditor" / "web"
    web_link.parent.mkdir(parents=True, exist_ok=True)
    if not web_link.exists():
        web_link.symlink_to(cfg.project_root / "pub_auditor" / "web")
    return replace(cfg, project_root=isolated_root)


def _wait_for_status(client, job_id: str, target: set[str], timeout: float = 5.0) -> dict:
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/audit/{job_id}")
        if r.status_code == 200 and r.json()["status"] in target:
            return r.json()
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached {target}; last={r.json() if r.status_code == 200 else r.status_code}")


def test_audit_returns_job_id_and_completes(_isolated_env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pub_auditor.config import load  # noqa: F401
    from pub_auditor.server import create_app

    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _seed_targets(tmp_path)
    cfg = _isolated_cfg(tmp_path)
    app = create_app(cfg)
    _stub_task_map(monkeypatch, {"success": True, "report_path": "/tmp/x.md",
                                  "summary": "ok", "error": None})
    client = TestClient(app)

    # /api/targets triggers scan
    r = client.get("/api/targets")
    assert r.status_code == 200

    r = client.post("/api/audit", json={"project": "demo", "tasks": ["review"]})
    assert r.status_code == 200
    body = r.json()
    assert "job_id" in body and body["status"] == "queued"

    final = _wait_for_status(client, body["job_id"], {"done"})
    assert final["tasks"][0]["status"] == "done"
    assert final["tasks"][0]["outcome"]["success"] is True


def test_audit_concurrency_cap(_isolated_env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pub_auditor.config import load  # noqa: F401
    from pub_auditor.server import create_app

    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_MAX_CONCURRENT", "1")
    _seed_targets(tmp_path)
    cfg = _isolated_cfg(tmp_path)
    app = create_app(cfg)

    # Make the task block until we release it.
    import threading
    block = threading.Event()
    release = threading.Event()

    def slow_task(cfg, project_path, project_name, on_proc_start=None):
        block.set()
        release.wait(timeout=5)
        return {"success": True, "report_path": "/tmp/x.md", "summary": "ok", "error": None}

    from pub_auditor import server as srv
    monkeypatch.setitem(srv.TASKS, "review", slow_task)
    client = TestClient(app)
    client.get("/api/targets")  # trigger scan

    r1 = client.post("/api/audit", json={"project": "demo", "tasks": ["review"]})
    assert r1.status_code == 200
    block.wait(timeout=2)

    r2 = client.post("/api/audit", json={"project": "demo", "tasks": ["review"]})
    assert r2.status_code == 429, r2.text

    release.set()


def test_audit_cancel(_isolated_env, tmp_path, monkeypatch):
    """DELETE /api/audit/{id} on a multi-task job — second task should be
    skipped because cancel_event is checked between tasks."""
    from fastapi.testclient import TestClient

    from pub_auditor.server import create_app

    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _seed_targets(tmp_path)
    cfg = _isolated_cfg(tmp_path)
    app = create_app(cfg)

    from pub_auditor import server as srv

    # Quick first task so we have time to cancel before the second.
    def first(cfg, project_path, project_name, on_proc_start=None):
        # Synthesize a cancel as soon as the first task starts so the
        # between-task check on the second task skips it.
        job_store = app.state.job_store
        for j in job_store.all():
            if j.status == "running":
                j.cancel_event.set()
                break
        return {"success": True, "report_path": "/tmp/x.md", "summary": "ok", "error": None}

    def second(cfg, project_path, project_name, on_proc_start=None):
        return {"success": True, "report_path": "/tmp/y.md", "summary": "ok", "error": None}

    monkeypatch.setitem(srv.TASKS, "review", first)
    monkeypatch.setitem(srv.TASKS, "security", second)
    client = TestClient(app)
    client.get("/api/targets")

    r = client.post("/api/audit", json={"project": "demo", "tasks": ["review", "security"]})
    job_id = r.json()["job_id"]

    final = _wait_for_status(client, job_id, {"cancelled", "done"}, timeout=5.0)
    # First task ran, second was skipped due to cancel_event check.
    statuses = [t["status"] for t in final["tasks"]]
    assert statuses[0] == "done"
    assert statuses[1] == "cancelled"
    assert final["status"] == "cancelled"


def test_cancel_unknown_job_returns_404(_isolated_env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pub_auditor.server import create_app
    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _seed_targets(tmp_path)
    cfg = _isolated_cfg(tmp_path)
    client = TestClient(create_app(cfg))
    assert client.delete("/api/audit/does-not-exist").status_code == 404


def test_get_unknown_job(_isolated_env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pub_auditor.config import load  # noqa: F401
    from pub_auditor.server import create_app

    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _seed_targets(tmp_path)
    cfg = _isolated_cfg(tmp_path)
    client = TestClient(create_app(cfg))
    assert client.get("/api/audit/nope").status_code == 404
    assert client.delete("/api/audit/nope").status_code == 404


def test_audit_unknown_task_rejected(_isolated_env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pub_auditor.config import load  # noqa: F401
    from pub_auditor.server import create_app

    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _seed_targets(tmp_path)
    cfg = _isolated_cfg(tmp_path)
    client = TestClient(create_app(cfg))
    client.get("/api/targets")
    r = client.post("/api/audit", json={"project": "demo", "tasks": ["bogus"]})
    assert r.status_code == 400
