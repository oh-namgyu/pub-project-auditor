"""PR-F regressions: JSONL audit log + claude sandbox wrapper."""
from __future__ import annotations

import json
import sys
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
              "AUDITOR_CLAUDE_WRAPPER"):
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


def _wait_for_status(client, job_id: str, target: set, timeout: float = 5.0) -> dict:
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/audit/{job_id}")
        if r.status_code == 200 and r.json()["status"] in target:
            return r.json()
        time.sleep(0.05)
    raise AssertionError(f"job never reached {target}")


# ----- audit log -----

def test_audit_log_path_unset_is_noop(_isolated_env, tmp_path):
    from pub_auditor.audit_log import append
    append(None, {"foo": "bar"})  # must not raise


def test_audit_log_appends_jsonl(_isolated_env, tmp_path):
    from pub_auditor.audit_log import append
    log_path = tmp_path / "audit.log"
    append(log_path, {"job_id": "x", "status": "done"})
    append(log_path, {"job_id": "y", "status": "cancelled"})
    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 2
    a = json.loads(lines[0])
    b = json.loads(lines[1])
    assert a["job_id"] == "x" and a["status"] == "done"
    assert "ts" in a  # auto-injected
    assert b["job_id"] == "y"


def test_audit_log_path_loads_from_env(_isolated_env, tmp_path):
    from pub_auditor.config import load
    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_AUDIT_LOG_PATH", str(tmp_path / "audit.log"))
    cfg = load()
    assert cfg.audit_log_path == (tmp_path / "audit.log").resolve()


def test_audit_log_written_after_job(_isolated_env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pub_auditor.server import create_app

    audit_log = tmp_path / "audit.log"
    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_AUDIT_LOG_PATH", str(audit_log))
    _seed_targets(tmp_path)
    cfg = _isolated_cfg(tmp_path)
    app = create_app(cfg)
    from pub_auditor import server as srv

    def fake(cfg, project_path, project_name, on_proc_start=None):
        return {"success": True, "report_path": "/tmp/x.md", "summary": "ok",
                "error": None, "cost_usd": 0.05, "duration_ms": 100}

    monkeypatch.setitem(srv.TASK_MAP, "review", fake)
    client = TestClient(app)
    client.get("/api/targets")

    r = client.post("/api/audit", json={"project": "demo", "tasks": ["review"]})
    job_id = r.json()["job_id"]
    _wait_for_status(client, job_id, {"done"})

    assert audit_log.exists(), "audit log should have been written"
    record = json.loads(audit_log.read_text().strip())
    assert record["job_id"] == job_id
    assert record["status"] == "done"
    assert record["project"] == "demo"
    assert record["cost_usd"] == 0.05
    assert record["tasks"][0]["task"] == "review"
    assert record["tasks"][0]["status"] == "done"


# ----- sandbox wrapper -----

def test_wrapper_parses_with_shlex(_isolated_env, tmp_path):
    from pub_auditor.config import load
    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_CLAUDE_WRAPPER",
                         "nsjail -Mo --chroot /sandbox --")
    cfg = load()
    assert cfg.claude_wrapper == ("nsjail", "-Mo", "--chroot", "/sandbox", "--")


def test_wrapper_empty_is_no_op(_isolated_env, tmp_path):
    from pub_auditor.config import load
    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    cfg = load()
    assert cfg.claude_wrapper == ()


def test_wrapper_prepended_to_argv(_isolated_env, tmp_path, monkeypatch):
    """Patch the runner's bound subprocess.Popen and assert the wrapper tokens
    appear before the claude binary in the final argv."""
    captured = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self.returncode = 0
        def communicate(self, timeout=None):
            return ('{"result": "ok", "cost_usd": 0.0, "duration_ms": 1}', "")
        def terminate(self): pass
        def kill(self): pass

    # Drop a fake binary file so _resolve_bin returns it (instead of falling
    # through to shutil.which("claude")).
    fake_claude = tmp_path / "claude"
    fake_claude.write_text("#!/bin/sh\necho '{}'\n")
    fake_claude.chmod(0o755)

    from pub_auditor import runner
    monkeypatch.setattr(runner.subprocess, "Popen", FakePopen)

    res = runner.run(
        prompt="hi", project_path=tmp_path, claude_bin=str(fake_claude),
        wrapper=("nsjail", "-Mo", "--"),
    )
    assert res["success"] is True, f"unexpected: {res}"
    assert captured["args"][0:3] == ["nsjail", "-Mo", "--"]
    assert captured["args"][3] == str(fake_claude)


def test_wrapper_omitted_when_empty(_isolated_env, tmp_path, monkeypatch):
    captured = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            self.returncode = 0
        def communicate(self, timeout=None):
            return ('{"result": "ok", "cost_usd": 0.0, "duration_ms": 1}', "")
        def terminate(self): pass
        def kill(self): pass

    fake_claude = tmp_path / "claude"
    fake_claude.write_text("#!/bin/sh\necho '{}'\n")
    fake_claude.chmod(0o755)

    from pub_auditor import runner
    monkeypatch.setattr(runner.subprocess, "Popen", FakePopen)

    runner.run(prompt="hi", project_path=tmp_path, claude_bin=str(fake_claude))
    assert captured["args"][0] == str(fake_claude)
