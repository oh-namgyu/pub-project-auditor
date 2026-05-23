"""Security audit task."""
from __future__ import annotations

from pathlib import Path

from pub_auditor.config import Config
from pub_auditor.tasks._common import TaskOutcome, run_task

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


def run_security(cfg: Config, project_path: Path, project_name: str,
                 on_proc_start=None) -> TaskOutcome:
    return run_task(cfg, project_path, project_name, "security", PROMPT, _first_finding,
                    on_proc_start=on_proc_start)


def _first_finding(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- ") and "No findings" not in s:
            return s[2:202]
    return "No findings"
