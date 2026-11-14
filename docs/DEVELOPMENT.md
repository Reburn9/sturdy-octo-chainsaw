# Development workflow

Use Python 3.11–3.13 and the README setup. Runtime versions are pinned in `requirements.txt`; `requirements-dev.txt` adds Ruff and Coverage. `pyproject.toml` also exposes installable project metadata and optional development/PostgreSQL extras. Refresh the lock intentionally and test the supported Python versions after dependency upgrades.

The project has no JavaScript compilation step. Edit templates and local assets directly; Python changes reload under `runserver`. Run `ruff format .` after Python changes and include generated Django migrations when changing the schema.

## Optional browser smoke

```bash
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
python scripts/browser_smoke.py
```

The script creates a temporary SQLite database, generates isolated credentials, migrates and seeds it, and launches a disposable server on loopback port 8765. It does not modify your development database. If that port is in use, set `SMOKE_PORT` to a different port. The script uses installed Google Chrome/Chromium when available, or Playwright's downloaded Chromium. Set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` explicitly if needed.

It exercises real form submissions for dataset creation, invalid/valid imports, members, assignment, hidden independent votes, conflicting labels, manager adjudication, and CSV export. It also checks mobile overflow and navigation and records JavaScript errors. Screenshots are written to ignored `test-results/`; CI uploads them as a seven-day artifact.

## Testing concurrency

The default SQLite suite checks version conflicts deterministically. The PostgreSQL CI job additionally runs two simultaneous writers from separate database connections and verifies that exactly one advances a given version. That test is explicitly skipped under SQLite's in-memory test database; it does not pretend to establish cross-process concurrency from a sequential unit test.

## Working with a terminal AI assistant

Use the repository as the working directory. Ask for one concrete change from the roadmap, request the reasoning behind competing approaches, inspect the diff, and run the checks yourself. Keep a reviewable branch and real commits as you work. Example:

> Add versioned labeling guidelines. First inspect the existing service boundaries, propose the smallest schema change, then implement it with a migration and behavior tests. Explain how old votes retain the guidance they used.

When comparing assistant responses, favor correct invariants and understandable changes over extra features. Check that each proposed write respects roles, transactions, audit behavior, and stale versions. Use actual test output as evidence; do not accept invented pass counts, benchmarks, or claims about code that was not run.
