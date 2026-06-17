import argparse
import dataclasses

from pub_auditor import cli, config, scanner
from pub_auditor.tasks._common import TaskOutcome


def _cfg(tmp_path):
    repos = tmp_path / "repos"
    repos.mkdir()
    cfg = config.load(repos_dir_override=str(repos))
    cfg = dataclasses.replace(cfg, project_root=tmp_path / "proj")
    cfg.targets_path.parent.mkdir(parents=True, exist_ok=True)
    return cfg


def test_cmd_scan_writes_targets(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    rc = cli.cmd_scan(cfg, argparse.Namespace())
    assert rc == 0
    assert cfg.targets_path.exists()
    assert "[scan]" in capsys.readouterr().out


def test_cmd_run_invokes_task(tmp_path, monkeypatch, capsys):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(scanner, "find_target",
                        lambda c, name: {"path": str(tmp_path), "name": name})

    def fake_task(c, path, name) -> TaskOutcome:
        return {"success": True, "report_path": "report.md", "summary": "ok", "error": None}

    monkeypatch.setitem(cli.TASKS, "faketask", fake_task)
    rc = cli.cmd_run(cfg, argparse.Namespace(task="faketask", project="demo"))
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_cmd_run_missing_project(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(scanner, "find_target", lambda c, name: None)
    rc = cli.cmd_run(cfg, argparse.Namespace(task="x", project="nope"))
    assert rc == 2


def test_cmd_run_task_failure(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(scanner, "find_target",
                        lambda c, name: {"path": str(tmp_path), "name": name})

    def failing(c, path, name) -> TaskOutcome:
        return {"success": False, "report_path": None, "summary": None, "error": "boom"}

    monkeypatch.setitem(cli.TASKS, "faketask", failing)
    rc = cli.cmd_run(cfg, argparse.Namespace(task="faketask", project="demo"))
    assert rc == 1
