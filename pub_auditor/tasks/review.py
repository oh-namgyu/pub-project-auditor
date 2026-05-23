"""Code review task."""
from __future__ import annotations

from pathlib import Path

from pub_auditor.config import Config
from pub_auditor.tasks._common import TaskOutcome, run_task

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
    return run_task(cfg, project_path, project_name, "review", PROMPT)
