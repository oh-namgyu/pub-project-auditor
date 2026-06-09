"""CLI entry point: python -m pub_auditor.cli <command> [...]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pub_auditor import scanner
from pub_auditor.config import Config, ConfigError, load
from pub_auditor.tasks import review, security
from pub_auditor.tasks._common import TaskOutcome

TASKS = {
    "review": review.run_review,
    "security": security.run_security,
}


def _load_target(cfg: Config, name: str) -> tuple[Path, str] | None:
    if not cfg.targets_path.is_file():
        scanner.write_targets(cfg, scanner.scan(cfg))
    data = json.loads(cfg.targets_path.read_text())
    for t in data.get("targets", []):
        if t.get("name") == name:
            return Path(t["path"]), t["name"]
    return None


def cmd_scan(cfg: Config, _args: argparse.Namespace) -> int:
    targets = scanner.scan(cfg)
    path = scanner.write_targets(cfg, targets)
    by_origin: dict[str, int] = {}
    for t in targets:
        by_origin[t.origin] = by_origin.get(t.origin, 0) + 1
    print(f"[scan] {len(targets)} repos in {cfg.repos_dir} -> {path}")
    print(f"  by origin: {by_origin}")
    return 0


def cmd_run(cfg: Config, args: argparse.Namespace) -> int:
    target = _load_target(cfg, args.project)
    if target is None:
        print(f"[run] project not found: {args.project}", file=sys.stderr)
        return 2
    project_path, project_name = target
    fn = TASKS[args.task]
    print(f"[run] {args.task} on {project_name} ({project_path})")
    outcome: TaskOutcome = fn(cfg, project_path, project_name)
    if outcome["success"]:
        print(f"[run] OK -> {outcome['report_path']}")
        if outcome["summary"]:
            print(f"  summary: {outcome['summary']}")
        return 0
    print(f"[run] FAIL: {outcome['error']}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="pub-auditor", description="Audit local Git repos with Claude Code")
    parser.add_argument("--repos-dir", help="Override AUDITOR_REPOS_DIR")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="Scan repos and write targets.json")

    p_run = sub.add_parser("run", help="Run a task on a single project")
    p_run.add_argument("task", choices=sorted(TASKS.keys()))
    p_run.add_argument("project")

    args = parser.parse_args()

    try:
        cfg = load(repos_dir_override=args.repos_dir)
    except ConfigError as e:
        print(f"[config] {e}", file=sys.stderr)
        return 4

    if args.command == "scan":
        return cmd_scan(cfg, args)
    if args.command == "run":
        return cmd_run(cfg, args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
