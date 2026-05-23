"""Environment-driven configuration. No paths default to the user's home directory."""
from __future__ import annotations

import os
import shlex
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
    auth_token: Optional[str]
    max_concurrent: int
    cost_usd_max: Optional[float]
    tools: str
    audit_log_path: Optional[Path]
    claude_wrapper: tuple[str, ...]

    @property
    def targets_path(self) -> Path:
        return self.project_root / "config" / "targets.json"

    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def is_loopback(self) -> bool:
        return self.host in ("127.0.0.1", "::1", "localhost")


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

    host = os.environ.get("AUDITOR_HOST", "127.0.0.1")
    auth_token = os.environ.get("AUDITOR_TOKEN", "").strip() or None

    # Non-loopback bind = network-reachable. Refuse to start without a token,
    # otherwise the /api/audit endpoint becomes a free remote-code-trigger
    # (spawns claude on whatever paths are in targets.json, bills the user).
    if host not in ("127.0.0.1", "::1", "localhost") and not auth_token:
        raise ConfigError(
            f"AUDITOR_HOST={host} binds beyond loopback, but AUDITOR_TOKEN is not set. "
            "Either restore AUDITOR_HOST=127.0.0.1 or set AUDITOR_TOKEN to a long random secret."
        )

    cost_max_raw = os.environ.get("AUDITOR_COST_USD_MAX", "").strip()
    try:
        cost_usd_max = float(cost_max_raw) if cost_max_raw else None
    except ValueError as e:
        raise ConfigError(f"AUDITOR_COST_USD_MAX must be a number; got {cost_max_raw!r}") from e

    audit_log_raw = os.environ.get("AUDITOR_AUDIT_LOG_PATH", "").strip()
    audit_log_path = Path(audit_log_raw).expanduser().resolve() if audit_log_raw else None

    wrapper_raw = os.environ.get("AUDITOR_CLAUDE_WRAPPER", "").strip()
    # shlex preserves quoted args ("--chroot=/sandbox dir with spaces") while
    # still splitting on whitespace — safer than a naive str.split.
    claude_wrapper = tuple(shlex.split(wrapper_raw)) if wrapper_raw else ()

    return Config(
        repos_dir=repos_dir,
        owners=owners,
        port=int(os.environ.get("AUDITOR_PORT", "6020")),
        host=host,
        claude_bin=os.environ.get("CLAUDE_BIN") or None,
        model=os.environ.get("AUDITOR_MODEL", "sonnet"),
        timeout_sec=int(os.environ.get("AUDITOR_TIMEOUT_SEC", "1800")),
        project_root=_project_root(),
        auth_token=auth_token,
        max_concurrent=max(1, int(os.environ.get("AUDITOR_MAX_CONCURRENT", "2"))),
        cost_usd_max=cost_usd_max,
        tools=os.environ.get("AUDITOR_TOOLS", "Read,Glob,Grep"),
        audit_log_path=audit_log_path,
        claude_wrapper=claude_wrapper,
    )
