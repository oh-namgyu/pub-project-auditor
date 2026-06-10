"""Token-gate regression. Locks down /api/audit etc. when AUDITOR_HOST is
non-loopback, and verifies the loopback default stays open (current behavior)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def _isolated_env(monkeypatch):
    """Strip relevant env so each test starts clean."""
    for k in ("AUDITOR_REPOS_DIR", "AUDITOR_HOST", "AUDITOR_TOKEN",
              "AUDITOR_PORT", "AUDITOR_OWNERS"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_non_loopback_host_without_token_rejects(_isolated_env, tmp_path):
    from pub_auditor.config import ConfigError, load
    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_HOST", "0.0.0.0")
    with pytest.raises(ConfigError, match="AUDITOR_TOKEN"):
        load()


def test_non_loopback_host_with_token_loads(_isolated_env, tmp_path):
    from pub_auditor.config import load
    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_HOST", "0.0.0.0")
    _isolated_env.setenv("AUDITOR_TOKEN", "s3cret-long-random")
    cfg = load()
    assert cfg.auth_token == "s3cret-long-random"
    assert cfg.host == "0.0.0.0"
    assert not cfg.is_loopback


def test_loopback_default_no_token_required(_isolated_env, tmp_path):
    from pub_auditor.config import load
    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    cfg = load()
    assert cfg.auth_token is None
    assert cfg.is_loopback


def test_protected_endpoint_blocks_without_token(_isolated_env, tmp_path):
    from fastapi.testclient import TestClient

    from pub_auditor.config import load
    from pub_auditor.server import create_app

    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_HOST", "0.0.0.0")
    _isolated_env.setenv("AUDITOR_TOKEN", "tok-abc-123")
    cfg = load()
    client = TestClient(create_app(cfg))

    # health is unauthenticated by design — sanity check
    assert client.get("/api/health").status_code == 200
    # protected endpoint without token
    assert client.get("/api/targets").status_code == 401
    # with bad token
    r = client.get("/api/targets", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    # with right token (header form)
    r = client.get("/api/targets", headers={"Authorization": "Bearer tok-abc-123"})
    assert r.status_code == 200
    # query-param token is NOT accepted on regular endpoints anymore — only the
    # SSE /events route honors ?token= (EventSource can't set headers). This
    # keeps the secret out of access logs for everything else.
    r = client.get("/api/targets?token=tok-abc-123")
    assert r.status_code == 401


def test_query_token_allowed_only_on_sse(_isolated_env, tmp_path):
    """?token= works for the SSE events endpoint but not for other routes."""
    from fastapi.testclient import TestClient

    from pub_auditor.config import load
    from pub_auditor.server import create_app

    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    _isolated_env.setenv("AUDITOR_HOST", "0.0.0.0")
    _isolated_env.setenv("AUDITOR_TOKEN", "tok-abc-123")
    cfg = load()
    client = TestClient(create_app(cfg))

    # Unknown job → 404 (not 401) proves the query token passed the gate.
    r = client.get("/api/audit/nope/events?token=tok-abc-123")
    assert r.status_code == 404
    # Wrong query token on the SSE route is still rejected.
    r = client.get("/api/audit/nope/events?token=wrong")
    assert r.status_code == 401


def test_loopback_no_token_endpoint_open(_isolated_env, tmp_path):
    from fastapi.testclient import TestClient

    from pub_auditor.config import load
    from pub_auditor.server import create_app

    _isolated_env.setenv("AUDITOR_REPOS_DIR", str(tmp_path))
    cfg = load()
    client = TestClient(create_app(cfg))
    # Loopback + no token → /api/targets should respond (200, body may be empty)
    assert client.get("/api/targets").status_code == 200
