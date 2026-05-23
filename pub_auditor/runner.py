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


def run(
    prompt: str,
    project_path: Path,
    claude_bin: Optional[str],
    model: str = "sonnet",
    timeout_sec: int = 1800,
    tools: str = DEFAULT_TOOLS,
    on_proc_start: Optional[Callable[[subprocess.Popen], None]] = None,
) -> RunResult:
    if not project_path.is_dir():
        return RunResult(success=False, text="", cost_usd=None, duration_ms=None,
                         error=f"project_path not found: {project_path}")
    binary = _resolve_bin(claude_bin)
    if not binary:
        return RunResult(success=False, text="", cost_usd=None, duration_ms=None,
                         error="claude binary not found on PATH (set CLAUDE_BIN or install Claude Code CLI)")
    # automation-gateway-allow: public-release project — external users won't have
    # the private automation-gateway gateway, so this must spawn claude directly.
    args = [
        binary,
        "-p", prompt,
        "--output-format", "json",
        "--model", model,
        "--no-session-persistence",
        "--tools", tools,
    ]
    # Popen + communicate(timeout=) instead of subprocess.run so a caller
    # (the job queue) can grab the Popen handle via on_proc_start and
    # SIGTERM it to implement cancellation.
    try:
        proc = subprocess.Popen(
            args, cwd=str(project_path), env={**os.environ},
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
