"""Shared task utilities: report saving, outcome type, task runner."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, TypedDict

if TYPE_CHECKING:
    from pub_auditor.config import Config


class TaskOutcome(TypedDict):
    success: bool
    report_path: str
    summary: str
    error: Optional[str]


def save_report(reports_dir: Path, project_name: str, task: str, body: str) -> Path:
    out_dir = reports_dir / project_name
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date.today().isoformat()}-{task}.md"
    path.write_text(body, encoding="utf-8")
    return path


def wrap_report(project: str, task: str, text: str, cost_usd: Optional[float], duration_ms: Optional[int]) -> str:
    meta = f"<!-- task={task} project={project} cost_usd={cost_usd} duration_ms={duration_ms} -->\n"
    return meta + text.strip() + "\n"


def first_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith("<!--"):
            return s[:200]
    return ""


def run_task(
    cfg: "Config",
    project_path: Path,
    project_name: str,
    task_name: str,
    prompt: str,
    extract_summary: Optional[Callable[[str], str]] = None,
    on_proc_start: Optional[Callable] = None,
) -> TaskOutcome:
    from pub_auditor import runner  # local import keeps the task→runner edge one-way

    result = runner.run(
        prompt, project_path,
        claude_bin=cfg.claude_bin, model=cfg.model, timeout_sec=cfg.timeout_sec,
        on_proc_start=on_proc_start,
    )
    if not result["success"]:
        return TaskOutcome(success=False, report_path="", summary="",
                           error=result["error"] or "unknown")
    body = wrap_report(project_name, task_name, result["text"], result["cost_usd"], result["duration_ms"])
    path = save_report(cfg.reports_dir, project_name, task_name, body)
    summary = (extract_summary or first_line)(result["text"])
    return TaskOutcome(success=True, report_path=str(path), summary=summary, error=None)
