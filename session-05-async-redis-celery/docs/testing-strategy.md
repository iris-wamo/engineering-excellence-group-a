# Shared Foundation Integration Tests

The shared package owns its independent helper tests. This repository tests the application's adoption of those helpers while preserving the existing workflow and JWT/RBAC behavior.

## Focused checks

From the Session 4 directory:

```bash
uv sync --locked
make test-foundations
uv run pytest tests/unit tests/test_enum_values.py
uv run ruff check app/api/dependencies/deps.py app/core/config.py app/core/exceptions.py app/main.py app/schemas/user.py app/schemas/project.py app/schemas/task.py app/services/project_service.py app/services/task_service.py scripts/demo_shared_package.py tests/integration/test_shared_foundations.py
uv run mypy app
make demo-shared
```

Focused tests require valid app settings but no running database. `tests/conftest.py` supplies a test-only JWT key. The foundation HTTP fixture replaces database/principal dependencies and restores overrides in `finally`. The unauthenticated-route case restores the real principal resolver and verifies bearer protection still returns 401.

| Contract | Evidence |
| --- | --- |
| Settings | Shared base used without losing database aliases or JWT fields |
| Pagination | All three list endpoints preserve fields/defaults and reject invalid query values |
| Resource/auth errors | Existing status codes, JSON envelopes, and bearer challenge headers |
| Request tracing | Health, list, validation, and error responses include a request ID |
| Authentication | Protected routes still reject requests without bearer tokens |
| OpenAPI | Existing page/page-size query constraints remain visible |
| Domain behavior | Existing service/workflow/enum tests remain regression coverage |

## Full regression suite

`make test` includes the existing application, authentication, workflow, database, and import suites. Use dedicated PostgreSQL/MongoDB services and migrate the database selected by `TEST_DATABASE_URL` before running it. Existing integration tests commit records, so use disposable data rather than a database containing work you need to retain.

Package helper tests and package build/install checks are maintained in the independent package repository. This application dependency is pinned, so tests and Docker builds use a reproducible source revision without a sibling checkout.
