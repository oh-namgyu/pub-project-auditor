"""PR-I regressions: audit_log rotation + /api/audits pagination + TTL."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def _isolated_env(monkeypatch):
    for k in ("AUDITOR_REPOS_DIR", "AUDITOR_HOST", "AUDITOR_TOKEN",
              "AUDITOR_PORT", "AUDITOR_OWNERS", "AUDITOR_MAX_CONCURRENT",
              "AUDITOR_COST_USD_MAX", "AUDITOR_TOOLS",
              "AUDITOR_ENV_PASSTHROUGH", "AUDITOR_AUDIT_LOG_PATH",
              "AUDITOR_CLAUDE_WRAPPER", "AUDITOR_AUDIT_LOG_MAX_BYTES",
              "AUDITOR_AUDIT_LOG_BACKUPS", "AUDITOR_JOB_TTL_SECONDS"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def _isolated_cfg(repos_dir: Path):
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


def _seed_targets(repos_dir: Path) -> None:
    (repos_dir / "demo").mkdir()


# ----- rotation -----

def test_rotation_at_threshold(_isolated_env, tmp_path, monkeypatch):
    """Active file past max_bytes → .1; new writes restart at empty file."""
    from pub_auditor.audit_log import append

    log = tmp_path / "audit.log"
    monkeypatch.setenv("AUDITOR_AUDIT_LOG_MAX_BYTES", "200")  # tiny threshold
    monkeypatch.setenv("AUDITOR_AUDIT_LOG_BACKUPS", "3")

    for i in range(10):
        append(log, {"i": i, "padding": "x" * 50})

    assert log.exists()
    # At least one rotation must have happened — .1 exists.
    assert (tmp_path / "audit.log.1").exists()


def test_rotation_keeps_n_backups(_isolated_env, tmp_path, monkeypatch):
    """N+1 rotations leave at most N backup files (oldest unlinked)."""
    from pub_auditor.audit_log import _rotate_if_needed

    log = tmp_path / "audit.log"
    monkeypatch.setenv("AUDITOR_AUDIT_LOG_BACKUPS", "2")

    # Manually create a current file + 2 prior backups.
    log.write_text("active\n")
    (tmp_path / "audit.log.1").write_text("backup1\n")
    (tmp_path / "audit.log.2").write_text("backup2\n")

    _rotate_if_needed(log, max_bytes=1, backups=2)

    # log → .1, old .1 → .2, old .2 → unlinked.
    assert not log.exists()
    assert (tmp_path / "audit.log.1").read_text() == "active\n"
    assert (tmp_path / "audit.log.2").read_text() == "backup1\n"
    assert not (tmp_path / "audit.log.3").exists()


# ----- pagination + TTL -----

def test_audits_pagination(_isolated_env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pub_auditor.server import create_app

    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_MAX_CONCURRENT", "10")
    _seed_targets(tmp_path)
    cfg = _isolated_cfg(tmp_path)
    app = create_app(cfg)
    store = app.state.job_store

    # Synthesize 5 jobs directly so we don't have to run the queue.
    import asyncio
    async def _seed():
        for _ in range(5):
            await store.create("demo", ["review"])
    asyncio.run(_seed())

    client = TestClient(app)

    r = client.get("/api/audits?limit=2&offset=0")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["jobs"]) == 2

    r = client.get("/api/audits?limit=2&offset=4")
    assert r.status_code == 200
    assert len(r.json()["jobs"]) == 1


def test_audits_limit_clamped(_isolated_env, tmp_path):
    from fastapi.testclient import TestClient

    from pub_auditor.server import create_app

    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _seed_targets(tmp_path)
    cfg = _isolated_cfg(tmp_path)
    client = TestClient(create_app(cfg))

    r = client.get("/api/audits?limit=99999&offset=-5")
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 200
    assert body["offset"] == 0


def test_job_ttl_sweeps_old_jobs(_isolated_env, tmp_path):
    import asyncio

    from pub_auditor.jobs import JobStore

    store = JobStore(max_concurrent=10, ttl_seconds=1)

    async def _seed():
        return await store.create("demo", ["review"])

    job = asyncio.run(_seed())
    job.status = "done"
    job.ended_at = time.time() - 5  # already 5s past expiry

    removed = store.sweep()
    assert removed == 1
    assert store.get(job.id) is None


def test_job_ttl_keeps_active_jobs(_isolated_env, tmp_path):
    import asyncio

    from pub_auditor.jobs import JobStore

    store = JobStore(max_concurrent=10, ttl_seconds=1)

    async def _seed():
        return await store.create("demo", ["review"])

    job = asyncio.run(_seed())
    job.status = "running"
    job.ended_at = None
    time.sleep(0.1)

    removed = store.sweep()
    assert removed == 0
    assert store.get(job.id) is not None
