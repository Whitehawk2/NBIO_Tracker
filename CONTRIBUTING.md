# Contributing

## Dev setup

```bash
git clone https://github.com/Whitehawk2/NBIO_Tracker.git
cd NBIO_Tracker

# Editable install with dev deps (pytest, ruff, mypy, …)
pip install -e ./app[dev]

# Run the suite
cd app
TZ=UTC python -m pytest                                # full suite
TZ=UTC python -m pytest --cov=nbio --cov-report=html   # local coverage report
ruff check nbio tests
ruff format --check nbio tests
mypy nbio --ignore-missing-imports
```

`TZ=UTC` matters: the timezone-dependent helpers in `routes/pages.py`
(`_local_hhmm`, `_group_events_by_local_day`) read the process tz at
runtime. CI sets `TZ=UTC` in the test job for the same reason.

## TDD policy

**Every new feature / bug fix lands a failing test in the same PR as
the implementation that makes it pass.** This is the only rule about how
new code arrives.

The mechanism: CI gates on `--cov-fail-under=90`. A PR that drops
coverage below 90% (configured in `app/pyproject.toml` →
`[tool.coverage.report]`) fails the `test` job and cannot merge.

If you find a bug in code that's already on `master`:

1. Write a failing test that captures the bug. Commit it.
2. Fix the bug. Commit it.
3. Open the PR. Reviewers can see the regression and the fix.

If you're retrofitting tests onto code that pre-dated this rule (rare —
the [#14 PR](https://github.com/Whitehawk2/NBIO_Tracker/pull/14) was the
last retrofit pass), say so in the PR description.

## Test layout

```
app/tests/
  conftest.py        # fixtures: conn / tmp_db / client / reset_broker / ...
  unit/              # pure functions, repo queries with :memory: SQLite
  api/               # FastAPI TestClient calls via dependency_overrides
  integration/       # SSE generator drives + WAL concurrency with file DB
  shell/             # shellcheck + bash -n + setup.sh --dry-run via subprocess
```

Markers: `@pytest.mark.integration` and `@pytest.mark.shell` are
auto-applied by path (see `conftest.py::pytest_collection_modifyitems`).
You don't need to add them yourself.

## Sharp edges to know before writing tests

These are reproduced from `CLAUDE.md`:

- **`sse.broker` is a module-level singleton imported by reference** in
  `routes/{events,devices,stream}.py`. The autouse `reset_broker`
  fixture in `conftest.py` mutates `broker._subs.clear()` — it does
  **not** replace `nbio.sse.broker`, because rebinding the attribute
  won't affect the names already imported by route modules.
- **`sqlite3.Connection` is immutable**. You can't `patch.object(conn,
  "execute", ...)`. To inject a failing execute, use the `FailingConn`
  proxy in `tests/unit/test_repo_error_paths.py`.
- **`TestClient` is single-threaded.** Real concurrency lives in
  `integration/test_concurrency.py`, which uses
  `httpx.AsyncClient(transport=ASGITransport(app))` plus a file-backed
  DB so WAL actually engages.
- **SSE tests drive the generator directly** via
  `sse_stream()` + iterating `response.body_iterator` with
  `asyncio.wait_for` — `httpx.AsyncClient.stream` hangs in-process
  because the generator's 20s keepalive blocks `aiter_text`.

## Style

- **ruff** for lint + format. No black. The config is in `app/pyproject.toml`.
- **mypy** for type-checking. `--ignore-missing-imports` is fine; the
  goal is to catch real type bugs, not chase third-party stubs.
- `from __future__ import annotations` only when needed.
- **No comments that restate the code.** Comments explain *why*, not *what*.

## Shell scripts

Every script starts with `#!/usr/bin/env bash` + `set -euo pipefail`.
Probe for required tools before running them. Pass `shellcheck
--severity=warning`. The shell CI job enforces this.

## When tests pass locally but fail in CI

- **Timezone:** set `TZ=UTC` locally too.
- **Python version:** CI runs against 3.12 and 3.13. If you only tested
  on one, install the other (`pyenv` or `uv`) before pushing.
- **Broker leaking:** check that `len(sse.broker._subs) == 0` at the
  end of any SSE test (the autouse fixture asserts this for you).

## Reporting

- Bugs / features: open an issue. Link from your PR.
- Roadmap: `TODO.md` is the source of truth, kept in sync manually with
  the GitHub issues it links to.
