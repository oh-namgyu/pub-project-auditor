# Security policy

## Reporting a vulnerability

If you've found a security issue in `pub-project-auditor`, **please do not file a public GitHub issue**. Instead, report it privately via [GitHub Security Advisories](https://github.com/oh-namgyu/pub-project-auditor/security/advisories/new).

I'll acknowledge within 7 days and aim for a fix within 30 days for confirmed issues. Coordinated disclosure: please give me time to publish a patched release before disclosing publicly.

## Threat model & non-goals

`pub-project-auditor` runs **locally**, spawns the `claude` CLI as a subprocess against repositories the operator has explicitly opted into, and writes Markdown reports under `reports/`. The default deployment binds to `127.0.0.1`; any other `AUDITOR_HOST` value **requires** `AUDITOR_TOKEN` and the server refuses to start otherwise.

Trust boundary (see [README → Trust boundary](README.md#trust-boundary-read-before-pointing-this-at-someone-elses-code)):

- **The repos being audited are untrusted input.** Their READMEs, source files, and config are fed to Claude as prompt context. A hostile repo can attempt prompt injection. The default `--tools` allowlist (`Read,Glob,Grep`) is read-only and contains the blast radius; treat audit reports as advisory when the target repo isn't yours.
- **Prompts (including target-repo excerpts) leave the machine** via Claude Code → Anthropic's API. Secrets present in target repos will flow upstream.
- **`AUDITOR_REPOS_DIR` is the trust root**, but every subdirectory under it is potentially hostile content.

The threat model **excludes**:

- An attacker with shell access to the host running the server.
- A misconfigured `claude` CLI that wasn't installed by the operator.
- Multi-tenant exposure beyond the token gate (no per-user audit log, no quota enforcement at the user layer).

In-scope concerns I want to hear about:

- Token-gate bypass on any `/api/*` endpoint that isn't `/api/health`.
- Path traversal via the `project` / `file` parameters on `/api/report`.
- Command/argument injection in the path from `AUDITOR_REPOS_DIR` → scanner → `pub_auditor.runner.run` → `claude` subprocess.
- A prompt-injection vector that escapes the read-only tool allowlist (e.g., causes Claude to fetch external URLs or exfiltrate environment).
- XSS in the dashboard's Markdown rendering (`marked` + `DOMPurify`) given a hostile report body.
- Supply-chain risk in the dependency tree (Dependabot is on, but please flag a confirmed exploit).

## Supported versions

Latest `main` only.
