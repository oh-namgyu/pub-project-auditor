# Changelog

All notable changes to pub-project-auditor.

## Unreleased — 2026-05-23

### Observability & extension
- **JSONL audit log.** `AUDITOR_AUDIT_LOG_PATH` activates an append-only log file with one record per completed job (`ts`, `job_id`, `project`, `status`, `started_at`, `ended_at`, `cost_usd`, per-task outcomes, `error`). No-op when unset.
- **Claude sandbox wrapper.** `AUDITOR_CLAUDE_WRAPPER` (shlex-split) prepends arbitrary tokens to the claude argv — e.g. `nsjail -Mo --chroot /sandbox --` or `firejail --noprofile --net=none`. Operator owns wrapper correctness.

### Security
- **`AUDITOR_TOKEN` auth gate.** Any non-loopback `AUDITOR_HOST` (anything other than `127.0.0.1` / `::1` / `localhost`) now requires `AUDITOR_TOKEN` and the server refuses to start otherwise. Previously a `0.0.0.0` bind exposed `/api/audit` to the network with no auth at all — anyone reachable could trigger claude spawns on the configured paths.
- **Bearer token on protected endpoints.** `/api/targets`, `/api/rescan`, `/api/targets/toggle`, `/api/audit*`, `/api/reports`, `/api/report` accept either `Authorization: Bearer <token>` or `?token=<token>`, compared with `hmac.compare_digest`. Loopback default with no token configured stays open for backward compat.
- **Subprocess env allowlist.** The claude subprocess now receives only `PATH`/`HOME`/`USER`/`LANG`/`LC_*`/`TERM` plus anything prefixed `ANTHROPIC_`, `CLAUDE_`, `AWS_BEDROCK_`, `GCP_VERTEX_`. App secrets sitting in the operator's shell no longer leak upstream. `AUDITOR_ENV_PASSTHROUGH=FOO,BAR` extends the list.
- **Server-controlled `--tools` allowlist.** `AUDITOR_TOOLS` (default `Read,Glob,Grep`) is read once from config and threaded through every task — callers can no longer override per request.

### Added
- **Async job queue.** `POST /api/audit` returns `{job_id, status: "queued"}` immediately instead of blocking for up to `AUDITOR_TIMEOUT_SEC` (1800 s default). Progress streams via SSE; jobs are cancellable.
  - `GET /api/audit/{job_id}` — snapshot
  - `DELETE /api/audit/{job_id}` — SIGTERMs the running claude subprocess
  - `GET /api/audit/{job_id}/events` — Server-Sent Events stream (`job_started` / `task_started` / `task_done` / `job_ended`, with 25 s keepalive)
  - `GET /api/audits` — list all jobs
- **Concurrency cap.** `AUDITOR_MAX_CONCURRENT` (default 2) caps queued + running jobs; past the cap, `POST /api/audit` returns 429.
- **Per-job cost cap.** `AUDITOR_COST_USD_MAX` (default unset) stops a job once the accumulated Claude cost exceeds the cap; remaining tasks are marked `cancelled` with a budget-overrun error.
- **Dashboard Cancel button** + EventSource-driven progress line.
- **`run_task` helper** (`tasks/_common.py`) — extracted shared task plumbing; `review.py` / `security.py` now one-liners that delegate.
- **GitHub Actions CI** runs pytest on a 3.9 / 3.11 / 3.12 matrix on every push and PR.
- **Dependabot** — weekly pip + github-actions updates.
- **`SECURITY.md`** — private reporting via GitHub Security Advisories with the trust boundary and in-scope list.
- **Test suite** (`tests/test_auth.py`, `tests/test_jobs.py`, `tests/test_hardening.py`) — 18 cases covering auth gate, job lifecycle, cancellation, concurrency cap, cost cap, env allowlist, tools config.

### Changed
- **`runner.py` switched from `subprocess.run` to `subprocess.Popen` + `communicate(timeout=)`** so the job worker can grab the proc handle (via the new `on_proc_start` hook) and SIGTERM it. Negative `returncode` or `130` (SIGINT) map to `error="cancelled"` for a clear UI signal.
- **README "Trust boundary" subsection** spells out that audited repos are untrusted input, prompt-injection is in scope, and prompts (including target-repo excerpts) flow upstream to Anthropic's API.

## v0.1.0 — 2026-05-13

- Initial public release.
