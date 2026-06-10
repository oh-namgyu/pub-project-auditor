"""Path-scrubbing helpers for non-loopback deployments.

When AUDITOR_MASK_PATHS is enabled the server strips absolute filesystem paths
(which embed the operator's home directory) from API responses before they
leave the process. These helpers are pure functions over plain dicts so they
can be unit-tested in isolation and reused by every route that emits a path.
"""
from __future__ import annotations

from pathlib import Path

MASK = "<masked>"

# Back-compat alias: server.py historically exposed this as `_MASK`.
_MASK = MASK


def mask_target_path(t: dict) -> dict:
    """Replace a target dict's absolute `path` with `<masked>/<name>`."""
    return {**t, "path": f"{MASK}/{t.get('name', '')}"}


def mask_targets_response(data: dict) -> dict:
    """Strip absolute filesystem paths from the /api/targets response.

    Replaces `repos_dir` with the sentinel '<masked>' and each path field
    (`targets[].path` AND `excluded[].path`) with `<masked>/<name>`, preserving
    the name for client-side display and leaving the underlying targets.json
    untouched on disk (still used by /api/audit). Enabled by AUDITOR_MASK_PATHS=1
    for non-loopback deployments where the absolute home path would otherwise leak.
    """
    out = dict(data)
    out["repos_dir"] = MASK
    out["targets"] = [mask_target_path(t) for t in data.get("targets", [])]
    if "excluded" in data:
        out["excluded"] = [mask_target_path(t) for t in data.get("excluded", [])]
    return out


def mask_job_snapshot(snap: dict) -> dict:
    """Scrub absolute `report_path` from a job snapshot's per-task outcomes.

    A task outcome carries `report_path` = the on-disk report file, which
    embeds the operator's reports_dir (and thus home path). When masking is
    on, collapse it to its basename so the UI still shows which report was
    written without leaking the absolute layout.
    """
    out = dict(snap)
    tasks = []
    for t in snap.get("tasks", []):
        outcome = t.get("outcome")
        if isinstance(outcome, dict) and outcome.get("report_path"):
            rp = str(outcome["report_path"])
            outcome = {**outcome, "report_path": f"{MASK}/{Path(rp).name}"}
            t = {**t, "outcome": outcome}
        tasks.append(t)
    out["tasks"] = tasks
    return out
