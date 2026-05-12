"""Security audit task."""
from __future__ import annotations

from pathlib import Path

from pub_auditor import runner
from pub_auditor.config import Config
from pub_auditor.tasks._common import TaskOutcome, save_report, wrap_report

PROMPT = """\
You are performing a security audit on the project in the current working directory.

Inspect: source files, package.json/requirements.txt/pyproject.toml, .env*, config files, route handlers.
Produce a Markdown report with EXACTLY these sections:

# Security Audit Report

## 1. Secrets / Credentials
- Hardcoded API keys, tokens, passwords (file:line)
- Sensitive files missing from .gitignore

## 2. Dependency Risk
- Libraries with known CVEs
- Packages unmaintained for over a year

## 3. Code Vulnerabilities
- Missing input validation, injection points (SQL, command, XSS)
- Auth / authorization bypass risks
- Unsafe deserialization, eval, dynamic import

## 4. Network / Permissions
- 0.0.0.0 bindings, CORS *, unauthenticated endpoints
- File permission issues

## 5. Top 3 Fixes (priority order)
- For each: the exact change to make

Rules:
- No speculation. Cite real code + file:line.
- If a section has no findings, write "No findings.".
- Write in English. Output Markdown body only.
"""


def run_security(cfg: Config, project_path: Path, project_name: str) -> TaskOutcome:
    result = runner.run(
        PROMPT, project_path,
        claude_bin=cfg.claude_bin, model=cfg.model, timeout_sec=cfg.timeout_sec,
    )
    if not result["success"]:
        return TaskOutcome(success=False, report_path="", summary="",
                           error=result["error"] or "unknown")
    body = wrap_report(project_name, "security", result["text"], result["cost_usd"], result["duration_ms"])
    path = save_report(cfg.reports_dir, project_name, "security", body)
    summary = _first_finding(result["text"])
    return TaskOutcome(success=True, report_path=str(path), summary=summary, error=None)


def _first_finding(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- ") and "No findings" not in s:
            return s[2:202]
    return "No findings"
