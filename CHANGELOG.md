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

## [0.2.0](https://github.com/oh-namgyu/pub-project-auditor/compare/v0.1.0...v0.2.0) (2026-06-17)


### Features

* **audit:** async jobs — SSE progress + cancel + concurrency cap ([f2aece1](https://github.com/oh-namgyu/pub-project-auditor/commit/f2aece1d5048cdc7b6cd5846c98bd7e798e629a3))
* JSONL audit log + AUDITOR_CLAUDE_WRAPPER for sandboxing ([3811ca2](https://github.com/oh-namgyu/pub-project-auditor/commit/3811ca24b9e77857fb0fa2f76fb9f3dca80b5b5a))
* **lifecycle:** audit-log rotation + /api/audits pagination + job TTL ([fb23e22](https://github.com/oh-namgyu/pub-project-auditor/commit/fb23e22e26303bafc7f175ba2ac8d0472337ed51))
* **server:** AUDITOR_MASK_PATHS option scrubs /api/targets absolute paths ([45df804](https://github.com/oh-namgyu/pub-project-auditor/commit/45df804f03600d69643fe4ded81264eba2909355))


### Bug Fixes

* close path-mask leak, restore cost cap, fix dashboard auth and job lifecycle ([9050148](https://github.com/oh-namgyu/pub-project-auditor/commit/90501480b6c2b5729cad3ec897f9dfd7b28488d5))
* **docker:** keep README.md in build context ([95bb1fa](https://github.com/oh-namgyu/pub-project-auditor/commit/95bb1fa0c2200ad65d049e3d3d49304bb7f93c13))


### Security

* AUDITOR_TOKEN gate + run_task helper + README trust boundary ([43557ff](https://github.com/oh-namgyu/pub-project-auditor/commit/43557ff43e3df8c778235d46bac5b886ae74b93f))
* env allowlist + tools lockdown + per-job cost cap + CHANGELOG ([c67e4f6](https://github.com/oh-namgyu/pub-project-auditor/commit/c67e4f6f5a718d8f27b5f8a476689317eccc4c8b))


### Documentation

* add Korean README (README_KOR.md) ([dda3404](https://github.com/oh-namgyu/pub-project-auditor/commit/dda3404d50640cdd5059938912e08d5df97add00))
* link Korean README from the top of README ([7562530](https://github.com/oh-namgyu/pub-project-auditor/commit/7562530a8396115d80fe2ab89fb88f26fc144c66))
* **readme:** mark roadmap items as planned v0.2+ / v0.3+ ([bc37f98](https://github.com/oh-namgyu/pub-project-auditor/commit/bc37f98bd949bfab02c7f34773518ae15ffe4a19))


### Continuous Integration

* GitHub Actions pytest + Dependabot + SECURITY.md ([c0b303a](https://github.com/oh-namgyu/pub-project-auditor/commit/c0b303a40bbb58bb5eb5af9027a19805cac2f1cd))
* ruff + pytest-cov + release-please ([844bac0](https://github.com/oh-namgyu/pub-project-auditor/commit/844bac086ac85b2b2a6f262ec9716eacd013b6bc))


### Build System

* Docker image (Python 3.12 slim + claude-code) + compose + ghcr publish ([6e76e71](https://github.com/oh-namgyu/pub-project-auditor/commit/6e76e71d44fcc5982311d93c8b3a52bccca6ca44))


### Code Refactoring

* extract job worker and path masking from server.py ([9c3e084](https://github.com/oh-namgyu/pub-project-auditor/commit/9c3e084efefb06d27b16d4d1cd4c00294f7b24e3))


### Tests

* cover the CLI (was 0%); add coverage floor + CONTRIBUTING ([6938f6e](https://github.com/oh-namgyu/pub-project-auditor/commit/6938f6e21b324b82111d75cd177d096b0232bc82))

## v0.1.0 — 2026-05-13

- Initial public release.
