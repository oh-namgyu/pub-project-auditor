"""Audit task registry — single source of truth for task name → runner fn.

Both the CLI (`pub_auditor.cli`) and the web server (`pub_auditor.server`) map a
task name (e.g. "review") to its runner here, so the two never drift.
"""
from __future__ import annotations

from pub_auditor.tasks import review, security

TASKS = {
    "review": review.run_review,
    "security": security.run_security,
}

__all__ = ["TASKS", "review", "security"]
