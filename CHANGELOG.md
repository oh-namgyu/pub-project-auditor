# Changelog

All notable changes to pub-project-auditor.

## Unreleased — 2026-05-23

### Lifecycle & rotation
- **JSONL audit log rotation.** Active file past `AUDITOR_AUDIT_LOG_MAX_BYTES` (default 10 MiB) is renamed to `<path>.1`; existing `.N` shifts down to `.N+1`. At most `AUDITOR_AUDIT_LOG_BACKUPS` (default 5) historical files are kept.
- **Job TTL + auto-cleanup.** Terminal-state jobs (`done` / `cancelled` / `failed`) older than `AUDITOR_JOB_TTL_SECONDS` (default 24 h) drop from `/api/audits` and the in-memory store on the next request — keeps a long-running process from growing the job map unboundedly.
- **`GET /api/audits` pagination.** `?limit=&offset=` (limit clamped to `[1, 200]`, offset to `[0, …)`); response includes `total`, `limit`, `offset`, `ttl_seconds`.
- **Docker image** (`Dockerfile` + `compose.yml` + `.github/workflows/docker.yml`). Bundles the Claude Code CLI; published to `ghcr.io/oh-namgyu/pub-project-auditor` on every main push and on `v*` tags.
- **`release-please` automation.** Conventional-commit messages drive an auto-opened release PR; merging it cuts a tag, bumps `pyproject.toml` + `CHANGELOG.md`, publishes a GitHub Release.
- **Ruff + pytest-cov in CI.** Lint job + coverage on the 3.12 matrix, summary uploaded to the GitHub Actions Job Summary.

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

## [0.2.0](https://github.com/oh-namgyu/pub-project-auditor/compare/v0.1.0...v0.2.0) (2026-05-30)


### Features

* **audit:** async jobs — SSE progress + cancel + concurrency cap ([b1ed086](https://github.com/oh-namgyu/pub-project-auditor/commit/b1ed0867d22f1d873ede8023e00f4c388a5776c6))
* JSONL audit log + AUDITOR_CLAUDE_WRAPPER for sandboxing ([e5bcbaf](https://github.com/oh-namgyu/pub-project-auditor/commit/e5bcbaf225a99d10c54f103ef481ea12f8d6d648))
* **lifecycle:** audit-log rotation + /api/audits pagination + job TTL ([d8be70c](https://github.com/oh-namgyu/pub-project-auditor/commit/d8be70c21c194191af477b9316507131a8b0556b))
* **server:** AUDITOR_MASK_PATHS option scrubs /api/targets absolute paths ([d0cb213](https://github.com/oh-namgyu/pub-project-auditor/commit/d0cb213a7d018c7fb46d539ef6ffe3da0e00621c))


### Bug Fixes

* **docker:** keep README.md in build context ([6ce5002](https://github.com/oh-namgyu/pub-project-auditor/commit/6ce500268fea925f4bcb041fcda33034ff1208b1))


### Security

* AUDITOR_TOKEN gate + run_task helper + README trust boundary ([6b1dfbd](https://github.com/oh-namgyu/pub-project-auditor/commit/6b1dfbd1040d6fe2e54f6f6c21e2fd5ad7a502a8))
* env allowlist + tools lockdown + per-job cost cap + CHANGELOG ([bf34266](https://github.com/oh-namgyu/pub-project-auditor/commit/bf34266d1dea3908e0b6de5409b612339ee7526a))


### Documentation

* **readme:** mark roadmap items as planned v0.2+ / v0.3+ ([d6ec4c0](https://github.com/oh-namgyu/pub-project-auditor/commit/d6ec4c0ed17450897d416943f46cb83aa8e09b79))


### Continuous Integration

* GitHub Actions pytest + Dependabot + SECURITY.md ([94a0b2a](https://github.com/oh-namgyu/pub-project-auditor/commit/94a0b2a01df800fbca41d77c32191947aabb8ed1))
* ruff + pytest-cov + release-please ([739cbc2](https://github.com/oh-namgyu/pub-project-auditor/commit/739cbc2a7579a954c7b9c91aaf2902c090c0ebed))


### Build System

* Docker image (Python 3.12 slim + claude-code) + compose + ghcr publish ([84f0d39](https://github.com/oh-namgyu/pub-project-auditor/commit/84f0d3979c5b9169c42fb9fa2175f17ada639c6b))

## v0.1.0 — 2026-05-13

- Initial public release.
