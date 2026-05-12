"""Shared task utilities: report saving, outcome type."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional, TypedDict


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
