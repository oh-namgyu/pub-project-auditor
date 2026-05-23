"""PR-D regressions: env allowlist + tools config + cost cap."""
from __future__ import annotations

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
              "AUDITOR_ENV_PASSTHROUGH"):
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


def test_env_allowlist_drops_arbitrary_secrets(_isolated_env, monkeypatch):
    """A random app secret in the operator's shell must NOT leak into the
    claude subprocess env. PATH/HOME/ANTHROPIC_* must pass through."""
    from pub_auditor.runner import _filtered_env

    monkeypatch.setenv("SOME_APP_SECRET", "xyz")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/Users/test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("CLAUDE_BIN", "/usr/local/bin/claude")

    env = _filtered_env()
    assert "SOME_APP_SECRET" not in env
    assert env.get("PATH") == "/usr/bin:/bin"
    assert env.get("HOME") == "/Users/test"
    assert env.get("ANTHROPIC_API_KEY") == "sk-ant-test"
    assert env.get("CLAUDE_BIN") == "/usr/local/bin/claude"


def test_env_passthrough_adds_to_allowlist(_isolated_env, monkeypatch):
    from pub_auditor.runner import _filtered_env

    monkeypatch.setenv("AUDITOR_ENV_PASSTHROUGH", "MY_CUSTOM_VAR, OTHER")
    monkeypatch.setenv("MY_CUSTOM_VAR", "yes")
    monkeypatch.setenv("OTHER", "also")
    monkeypatch.setenv("SHOULD_NOT_PASS", "nope")

    env = _filtered_env()
    assert env.get("MY_CUSTOM_VAR") == "yes"
    assert env.get("OTHER") == "also"
    assert "SHOULD_NOT_PASS" not in env


def test_tools_config_default(_isolated_env, tmp_path):
    from pub_auditor.config import load
    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    cfg = load()
    assert cfg.tools == "Read,Glob,Grep"


def test_tools_config_override(_isolated_env, tmp_path):
    from pub_auditor.config import load
    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_TOOLS", "Read,Glob")
    cfg = load()
    assert cfg.tools == "Read,Glob"


def test_cost_max_invalid(_isolated_env, tmp_path):
    from pub_auditor.config import ConfigError, load
    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_COST_USD_MAX", "not-a-number")
    with pytest.raises(ConfigError, match="AUDITOR_COST_USD_MAX"):
        load()


def test_cost_max_loads(_isolated_env, tmp_path):
    from pub_auditor.config import load
    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_COST_USD_MAX", "0.50")
    cfg = load()
    assert cfg.cost_usd_max == 0.50


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


def test_cost_cap_skips_remaining_tasks(_isolated_env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pub_auditor.server import create_app

    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_COST_USD_MAX", "0.10")
    _seed_targets(tmp_path)
    cfg = _isolated_cfg(tmp_path)
    app = create_app(cfg)
    from pub_auditor import server as srv

    # First task spends $0.20 — already over the $0.10 cap, so second task
    # should be skipped.
    def expensive(cfg, project_path, project_name, on_proc_start=None):
        return {"success": True, "report_path": "/tmp/x.md", "summary": "ok",
                "error": None, "cost_usd": 0.20, "duration_ms": 100}

    def second(cfg, project_path, project_name, on_proc_start=None):
        return {"success": True, "report_path": "/tmp/y.md", "summary": "ok",
                "error": None, "cost_usd": 0.01, "duration_ms": 100}

    monkeypatch.setitem(srv.TASK_MAP, "review", expensive)
    monkeypatch.setitem(srv.TASK_MAP, "security", second)
    client = TestClient(app)
    client.get("/api/targets")

    r = client.post("/api/audit", json={"project": "demo", "tasks": ["review", "security"]})
    job_id = r.json()["job_id"]
    final = _wait_for_status(client, job_id, {"cancelled", "done", "failed"})
    statuses = [t["status"] for t in final["tasks"]]
    assert statuses[0] == "done"
    assert statuses[1] == "cancelled"
    assert final["status"] == "cancelled"
    assert "cost cap" in (final["error"] or "")
