"""Claude Code CLI subprocess wrapper. Locates `claude` via PATH or CLAUDE_BIN env var."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional, TypedDict


class RunResult(TypedDict):
    success: bool
    text: str
    cost_usd: Optional[float]
    duration_ms: Optional[int]
    error: Optional[str]


def _resolve_bin(claude_bin: Optional[str]) -> Optional[str]:
    if claude_bin and Path(claude_bin).is_file():
        return claude_bin
    found = shutil.which("claude")
    return found


DEFAULT_TOOLS = "Read,Glob,Grep"

# Environment variables passed to the claude subprocess. Anything outside
# this allowlist is dropped — keeps unrelated app secrets in the operator's
# shell from leaking upstream and shrinks the surface a hostile target-repo
# prompt-injection can reach. Operators can extend via AUDITOR_ENV_PASSTHROUGH.
_BASE_ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR",
    "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES",
    "TERM", "TERMINFO",
})
_ENV_PREFIX_ALLOWLIST = ("ANTHROPIC_", "CLAUDE_", "AWS_BEDROCK_", "GCP_VERTEX_")


def _filtered_env() -> dict:
    """Build the env dict for the claude subprocess from the allowlist."""
    extra = {k.strip() for k in os.environ.get("AUDITOR_ENV_PASSTHROUGH", "").split(",") if k.strip()}
    allowed_keys = _BASE_ENV_ALLOWLIST | extra
    out: dict[str, str] = {}
    for k, v in os.environ.items():
        if k in allowed_keys or any(k.startswith(p) for p in _ENV_PREFIX_ALLOWLIST):
            out[k] = v
    return out


def run(
    prompt: str,
    project_path: Path,
    claude_bin: Optional[str],
    model: str = "sonnet",
    timeout_sec: int = 1800,
    tools: str = DEFAULT_TOOLS,
    on_proc_start: Optional[Callable[[subprocess.Popen], None]] = None,
    wrapper: tuple = (),
) -> RunResult:
    if not project_path.is_dir():
        return RunResult(success=False, text="", cost_usd=None, duration_ms=None,
                         error=f"project_path not found: {project_path}")
    binary = _resolve_bin(claude_bin)
    if not binary:
        return RunResult(success=False, text="", cost_usd=None, duration_ms=None,
                         error="claude binary not found on PATH (set CLAUDE_BIN or install Claude Code CLI)")
    # adaptagent-allow: public-release project — external users won't have
    # the private adaptAgent gateway, so this must spawn claude directly.
    args = [
        binary,
        "-p", prompt,
        "--output-format", "json",
        "--model", model,
        "--no-session-persistence",
        "--tools", tools,
    ]
    # Optional sandbox/wrapper prefix (nsjail, firejail, bwrap, etc.). The
    # operator is responsible for the wrapper's correctness — we just put its
    # tokens in front of the claude argv so subprocess starts in whatever
    # confinement the wrapper provides.
    if wrapper:
        args = list(wrapper) + args
    # Popen + communicate(timeout=) instead of subprocess.run so a caller
    # (the job queue) can grab the Popen handle via on_proc_start and
    # SIGTERM it to implement cancellation.
    try:
        proc = subprocess.Popen(
            args, cwd=str(project_path), env=_filtered_env(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except OSError as e:
        return RunResult(success=False, text="", cost_usd=None, duration_ms=None,
                         error=f"failed to spawn claude: {e}")
    if on_proc_start is not None:
        try:
            on_proc_start(proc)
        except Exception:
            pass
    try:
        stdout, stderr = proc.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return RunResult(success=False, text="", cost_usd=None, duration_ms=None,
                         error=f"timeout after {timeout_sec}s")
    if proc.returncode != 0:
        # SIGTERM from a cancel exits with negative returncode on POSIX,
        # 130 on SIGINT. Map both to a clear "cancelled" error so the UI
        # can show "cancelled by user" instead of a confusing exit code.
        if proc.returncode < 0 or proc.returncode == 130:
            return RunResult(success=False, text=stdout or "", cost_usd=None, duration_ms=None,
                             error="cancelled")
        return RunResult(success=False, text=stdout or "", cost_usd=None, duration_ms=None,
                         error=f"exit={proc.returncode} stderr={(stderr or '')[:500]}")
    return _parse(stdout)


def _parse(stdout: str) -> RunResult:
    stdout = stdout.strip()
    if not stdout:
        return RunResult(success=False, text="", cost_usd=None, duration_ms=None,
                         error="empty stdout")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        return RunResult(success=False, text=stdout, cost_usd=None, duration_ms=None,
                         error=f"invalid JSON output: {e}")
    text = data.get("result") or data.get("text") or ""
    if not text:
        return RunResult(success=False, text="", cost_usd=data.get("cost_usd"),
                         duration_ms=data.get("duration_ms"), error="empty result field")
    return RunResult(success=True, text=text,
                     cost_usd=data.get("cost_usd"),
                     duration_ms=data.get("duration_ms"), error=None)
