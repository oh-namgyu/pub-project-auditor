"""AUDITOR_MASK_PATHS regression.

Default-off keeps the existing /api/targets response shape (absolute paths,
backward-compatible). When on, repos_dir and targets[].path are scrubbed so a
non-loopback deploy doesn't leak the operator's home directory layout.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def _env(monkeypatch, tmp_path):
    for k in ("AUDITOR_REPOS_DIR", "AUDITOR_HOST", "AUDITOR_TOKEN",
              "AUDITOR_PORT", "AUDITOR_OWNERS", "AUDITOR_MASK_PATHS"):
        monkeypatch.delenv(k, raising=False)
    repos = tmp_path / "repos"
    repos.mkdir()
    monkeypatch.setenv("AUDITOR_REPOS_DIR", str(repos))
    return monkeypatch


def _seed_targets(cfg, names: list[str]) -> None:
    """Write a minimal targets.json so list_targets returns without scanning."""
    cfg.targets_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.targets_path.write_text(json.dumps({
        "generated_at": "2026-05-30T00:00:00",
        "repos_dir": str(cfg.repos_dir),
        "total": len(names),
        "kept": len(names),
        "enabled_count": len(names),
        "targets": [
            {"name": n, "path": str(cfg.repos_dir / n), "origin": "local",
             "language": "python", "has_git": False,
             "last_modified": "2026-05-30T00:00:00", "remote_url": None,
             "enabled": True}
            for n in names
        ],
    }))


def test_mask_paths_default_off_returns_absolute(_env):
    from pub_auditor.config import load
    from pub_auditor.server import create_app
    cfg = load()
    assert cfg.mask_paths is False
    _seed_targets(cfg, ["alpha", "beta"])
    client = TestClient(create_app(cfg))
    r = client.get("/api/targets")
    assert r.status_code == 200
    body = r.json()
    assert body["repos_dir"] == str(cfg.repos_dir)
    assert body["targets"][0]["path"] == str(cfg.repos_dir / "alpha")
    assert body["targets"][1]["path"] == str(cfg.repos_dir / "beta")


def test_mask_paths_on_scrubs_repos_dir_and_target_paths(_env):
    _env.setenv("AUDITOR_MASK_PATHS", "1")
    from pub_auditor.config import load
    from pub_auditor.server import create_app
    cfg = load()
    assert cfg.mask_paths is True
    _seed_targets(cfg, ["alpha", "beta"])
    client = TestClient(create_app(cfg))
    r = client.get("/api/targets")
    assert r.status_code == 200
    body = r.json()
    assert body["repos_dir"] == "<masked>"
    paths = [t["path"] for t in body["targets"]]
    assert paths == ["<masked>/alpha", "<masked>/beta"]
    # Other fields preserved.
    assert body["targets"][0]["name"] == "alpha"
    assert body["targets"][0]["enabled"] is True
    assert body["total"] == 2


def test_mask_paths_does_not_modify_targets_json_on_disk(_env):
    """Mask is response-only; the disk file remains authoritative for /api/audit
    which needs the real path to dispatch claude into the right cwd."""
    _env.setenv("AUDITOR_MASK_PATHS", "yes")
    from pub_auditor.config import load
    from pub_auditor.server import create_app
    cfg = load()
    _seed_targets(cfg, ["gamma"])
    real_path_before = json.loads(cfg.targets_path.read_text())["targets"][0]["path"]
    TestClient(create_app(cfg)).get("/api/targets")
    real_path_after = json.loads(cfg.targets_path.read_text())["targets"][0]["path"]
    assert real_path_before == real_path_after == str(cfg.repos_dir / "gamma")


@pytest.mark.parametrize("flag", ["0", "false", "no", "off", ""])
def test_mask_paths_flag_falsy_values(_env, flag):
    _env.setenv("AUDITOR_MASK_PATHS", flag)
    from pub_auditor.config import load
    cfg = load()
    assert cfg.mask_paths is False


@pytest.mark.parametrize("flag", ["1", "true", "yes", "on", "TRUE", "Yes"])
def test_mask_paths_flag_truthy_values(_env, flag):
    _env.setenv("AUDITOR_MASK_PATHS", flag)
    from pub_auditor.config import load
    cfg = load()
    assert cfg.mask_paths is True
