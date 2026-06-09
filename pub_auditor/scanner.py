"""Scan a directory of Git repos and write a targets.json file."""
from __future__ import annotations

import configparser
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pub_auditor.config import Config

Origin = Literal["local", "owned_remote", "external"]
Lang = Literal["python", "node", "mixed", "unknown"]


@dataclass
class Target:
    name: str
    path: str
    origin: Origin
    language: Lang
    has_git: bool
    last_modified: Optional[str]
    remote_url: Optional[str]
    enabled: bool = True


def _read_origin_url(project: Path) -> Optional[str]:
    git_config = project / ".git" / "config"
    if not git_config.is_file():
        return None
    parser = configparser.ConfigParser(strict=False)
    try:
        parser.read(git_config, encoding="utf-8")
    except configparser.Error:
        return None
    section = 'remote "origin"'
    if section in parser and "url" in parser[section]:
        return parser[section]["url"].strip()
    return None


def _extract_owner(remote_url: str) -> Optional[str]:
    """Extract the owner segment from common Git remote URL shapes.

    Supports:
      git@github.com:owner/repo.git
      https://github.com/owner/repo(.git)
      ssh://git@host/owner/repo.git
    Returns the lowercased owner, or None if it can't be parsed.
    """
    url = remote_url.strip()
    if "@" in url and ":" in url and "://" not in url:
        try:
            tail = url.split(":", 1)[1]
        except IndexError:
            return None
    else:
        if "://" not in url:
            return None
        tail = url.split("://", 1)[1].split("/", 1)
        if len(tail) < 2:
            return None
        tail = tail[1]
    parts = [p for p in tail.split("/") if p]
    if not parts:
        return None
    return parts[0].lower().removesuffix(".git")


def _classify(remote_url: Optional[str], owners: tuple[str, ...]) -> Origin:
    if remote_url is None:
        return "local"
    if not owners:
        return "owned_remote"
    owner = _extract_owner(remote_url)
    if owner and owner in owners:
        return "owned_remote"
    return "external"


def _detect_language(project: Path) -> Lang:
    has_py = (project / "requirements.txt").is_file() or (project / "pyproject.toml").is_file()
    has_node = (project / "package.json").is_file()
    if has_py and has_node:
        return "mixed"
    if has_py:
        return "python"
    if has_node:
        return "node"
    return "unknown"


def _last_modified(project: Path) -> Optional[str]:
    if (project / ".git").is_dir():
        try:
            out = subprocess.run(
                ["git", "-C", str(project), "log", "-1", "--format=%cI"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    try:
        return datetime.fromtimestamp(project.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def scan(cfg: Config) -> list[Target]:
    targets: list[Target] = []
    self_name = cfg.project_root.name
    for entry in sorted(cfg.repos_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name == self_name:
            continue
        remote_url = _read_origin_url(entry)
        targets.append(Target(
            name=entry.name,
            path=str(entry),
            origin=_classify(remote_url, cfg.owners),
            language=_detect_language(entry),
            has_git=(entry / ".git").is_dir(),
            last_modified=_last_modified(entry),
            remote_url=remote_url,
        ))
    return targets


def _existing_enabled(targets_path: Path) -> dict[str, bool]:
    if not targets_path.is_file():
        return {}
    try:
        data = json.loads(targets_path.read_text())
    except json.JSONDecodeError:
        return {}
    return {t["name"]: bool(t.get("enabled", True)) for t in data.get("targets", [])}


def write_targets(cfg: Config, targets: list[Target]) -> Path:
    cfg.targets_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _existing_enabled(cfg.targets_path)
    for t in targets:
        if t.name in existing:
            t.enabled = existing[t.name]
    kept = [t for t in targets if t.origin != "external"]
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "repos_dir": str(cfg.repos_dir),
        "total": len(targets),
        "kept": len(kept),
        "enabled_count": sum(1 for t in kept if t.enabled),
        "targets": [asdict(t) for t in kept],
        "excluded": [asdict(t) for t in targets if t.origin == "external"],
    }
    cfg.targets_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return cfg.targets_path


def set_enabled_bulk(cfg: Config, updates: dict[str, bool]) -> int:
    if not cfg.targets_path.is_file():
        return 0
    data = json.loads(cfg.targets_path.read_text())
    count = 0
    for t in data.get("targets", []):
        if t.get("name") in updates:
            t["enabled"] = bool(updates[t["name"]])
            count += 1
    data["enabled_count"] = sum(1 for t in data.get("targets", []) if t.get("enabled", True))
    cfg.targets_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return count
