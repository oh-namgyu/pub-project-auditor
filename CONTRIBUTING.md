# Contributing to pub-project-auditor

Thanks for your interest!

## Development setup

```bash
pip install -e .
pip install pytest pytest-cov httpx ruff
pytest
ruff check pub_auditor tests
```

## Guidelines

- **Never put real paths or credentials in the repo** — use placeholders like
  `/Users/alice` in examples (the auditor itself flags real paths).
- Add tests under `tests/` for any behavior change; CI enforces a coverage floor.
- Run `pytest` and `ruff check` before opening a PR; describe what changed and
  how you verified it.
