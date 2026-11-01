# Shared Package Application Integration

## Objective

Prove that Session 4 uses the independent shared package while preserving its HTTP contracts, task workflows, and JWT/RBAC protections.

## Scenario

Users, projects, and tasks need common pagination and errors. Requests need a correlation ID across success and failure responses. Reuse infrastructure while keeping domain and authorization policies in the application.

## Commands / Steps Used

From the Session 4 directory, with valid application settings:

```bash
uv sync --locked
make demo-shared
make test-foundations
uv run pytest tests/unit tests/test_enum_values.py
uv run mypy app
docker build -t taskflow-shared-integration:local .
```

For the complete application suite, configure disposable PostgreSQL/MongoDB services, migrate the dedicated test database, and run `make test`.

## Expected Behavior

- Installation uses the pinned package archive without requiring a nested clone.
- The executable demo validates shared pagination, error contracts, response fields, and request-ID cleanup.
- List/error response contracts remain unchanged.
- Invalid query values return 422; unauthenticated protected routes return 401 with a bearer challenge.
- Responses through the outer application include `X-Request-ID`, including error responses.
- Existing workflow and authorization rules remain app-owned.

## Actual Findings

The focused regression run passed 99 tests: shared-foundation HTTP integration, existing workflow/service/enum tests, and bearer-route protection checks. Application type checks passed for all 45 source files. The executable shared-package demo passed, and `uv lock --check` confirmed the pinned dependency metadata.

These results cover the integration and existing route protections; they do not claim a new run of the complete database-backed suite.

## Evidence

`tests/integration/test_shared_foundations.py` exercises the real FastAPI routing and outer middleware with isolated service dependencies. Existing workflow/service/enum tests cover domain regression. The source archive and exact commit are declared in `pyproject.toml` and locked by `uv.lock`.

The [testing strategy](../../docs/testing-strategy.md) provides the focused and database-backed verification commands. The [package PR](https://github.com/husnainmazhar45/taskflow-shared/pull/1) contains independent helper tests and package build checks.

## What We Learned

Application adoption is separate from building a reusable package. Pin the dependency source, retain HTTP compatibility, and keep authentication and business decisions outside shared infrastructure.
