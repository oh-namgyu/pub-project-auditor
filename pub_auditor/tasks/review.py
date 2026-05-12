"""Code review task."""
from __future__ import annotations

from pathlib import Path

from pub_auditor import runner
from pub_auditor.config import Config
from pub_auditor.tasks._common import TaskOutcome, first_line, save_report, wrap_report

PROMPT = """\
You are auditing the project in the current working directory.

Read README (if present), the main entry files, and a representative sample of source files.
Then produce a Markdown report with EXACTLY these sections:

# Code Review Report

## 1. Overview
- One-line summary / primary tech stack / key directories

## 2. Strengths
- 3-5 bullets on what is well designed

## 3. Issues
- Cite specific file paths + line numbers
- Mark priority (High / Medium / Low)

## 4. Reuse / Refactor Opportunities
- Duplicated logic, extractable utilities, places where a library would be a better fit

## 5. Next Steps
- 3 immediately actionable items

Rules:
- No speculation. Only cite files and lines you actually read.
- Keep code blocks short (under 10 lines).
- Write in English.
- Do not add sections beyond the five above.
- Output Markdown body only (do not wrap in code fences).
"""


def run_review(cfg: Config, project_path: Path, project_name: str) -> TaskOutcome:
    result = runner.run(
        PROMPT, project_path,
        claude_bin=cfg.claude_bin, model=cfg.model, timeout_sec=cfg.timeout_sec,
    )
    if not result["success"]:
        return TaskOutcome(success=False, report_path="", summary="",
                           error=result["error"] or "unknown error")
    body = wrap_report(project_name, "review", result["text"], result["cost_usd"], result["duration_ms"])
    path = save_report(cfg.reports_dir, project_name, "review", body)
    return TaskOutcome(success=True, report_path=str(path),
                       summary=first_line(result["text"]), error=None)
