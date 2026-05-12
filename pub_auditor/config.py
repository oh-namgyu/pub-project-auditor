"""Environment-driven configuration. No paths default to the user's home directory."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    repos_dir: Path
    owners: tuple[str, ...]
    port: int
    host: str
    claude_bin: Optional[str]
    model: str
    timeout_sec: int
    project_root: Path

    @property
    def targets_path(self) -> Path:
        return self.project_root / "config" / "targets.json"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load(repos_dir_override: Optional[str] = None) -> Config:
    repos_raw = repos_dir_override or os.environ.get("AUDITOR_REPOS_DIR", "").strip()
    if not repos_raw:
        raise ConfigError(
            "AUDITOR_REPOS_DIR is not set. Pass --repos-dir or set the env var. "
            "Example: AUDITOR_REPOS_DIR=/absolute/path/to/your/repos"
        )
    repos_dir = Path(repos_raw).expanduser().resolve()
    if not repos_dir.is_dir():
        raise ConfigError(f"AUDITOR_REPOS_DIR does not exist or is not a directory: {repos_dir}")

    owners_raw = os.environ.get("AUDITOR_OWNERS", "").strip()
    owners = tuple(o.strip().lower() for o in owners_raw.split(",") if o.strip())

    return Config(
        repos_dir=repos_dir,
        owners=owners,
        port=int(os.environ.get("AUDITOR_PORT", "6020")),
        host=os.environ.get("AUDITOR_HOST", "127.0.0.1"),
        claude_bin=os.environ.get("CLAUDE_BIN") or None,
        model=os.environ.get("AUDITOR_MODEL", "sonnet"),
        timeout_sec=int(os.environ.get("AUDITOR_TIMEOUT_SEC", "1800")),
        project_root=_project_root(),
    )
