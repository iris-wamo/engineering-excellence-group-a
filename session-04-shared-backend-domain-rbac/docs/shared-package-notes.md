# Shared Package Integration

This integration addresses [Build taskflow_shared Package](https://github.com/iris-wamo/engineering-excellence-group-a/issues/23) and [Shared Package Tests + Foundation Documentation](https://github.com/iris-wamo/engineering-excellence-group-a/issues/24).

## Dependency and ownership

The package is maintained in the separate [taskflow-shared repository](https://github.com/husnainmazhar45/taskflow-shared). The application pins its source archive to commit `82b2360ff5958b9a5f45d27d2e939ed8c73a1f3e`. `uv.lock` records the archive and resolved dependencies. `uv sync --locked` installs it without a local package clone; the Docker build uses the same declaration.

An optional package checkout under `packages/taskflow_shared/` remains separate and ignored by this repository. Package source and its independent tests are reviewed in the [package PR](https://github.com/husnainmazhar45/taskflow-shared/pull/1).

## Extraction and application usage

| Concern | Shared implementation | Application adapter |
| --- | --- | --- |
| Base settings | `config.BaseAppConfig` | `core/config.py` retains database and JWT settings |
| Common errors | `errors.AppHTTPException` and error contracts | `core/exceptions.py` retains resource/auth error names, status codes, messages, and headers |
| Pagination | `pagination.PaginationParams`, `PaginatedResponse[T]` | HTTP query adapter, three list schemas, task/project offset calculation |
| Response fields | `contracts.IdentifiableSchema`, `TimestampedSchema` | Task response inherits UUID and timestamp fields |
| Infrastructure enums | `enums.AppEnvironment`, `SortOrder` | Environment enum validates base settings; sorting is available without adding API behavior |
| Request correlation | `logging.RequestIDMiddleware` and context/filter helpers | `app.main:application` wraps the existing FastAPI app |

## Preserved contracts

- Pagination remains page 1 / size 10 by default, with page size 1–100 and invalid HTTP values rejected with 422. Generic responses retain exactly `items`, `page`, `page_size`, and `total`.
- Resource/auth errors retain `detail.error.code`, `detail.error.message`, existing status codes, and bearer-authentication headers.
- Existing JWT router protections, role checks, task transitions, transactions, history/activity writes, and database enums remain unchanged.
- `APP_ENV` accepts development/testing/staging/production. Database aliases and JWT settings remain app-owned.
- Request IDs are additive correlation hints, never authentication or authorization credentials. Valid incoming IDs are propagated; invalid or duplicate IDs are replaced. Context is cleared on success and failure. Applications may attach the shared logging filter to their own handlers; root logging is not configured on import.
- Serving `app.main:application` covers unhandled errors as well as normal responses. The inner FastAPI `app` remains available for OpenAPI and test dependency overrides.

## Boundaries and verification

Task/project/user models, status and priority rules, JWT token handling, RBAC policies, repositories, and import normalization remain in the application. No migration is introduced by this integration.

See [architecture boundaries](architecture-boundaries.md), [testing strategy](testing-strategy.md), and the [written demo](../demos/01-shared-package/demo.md). Package changes alone do not prove application adoption; the package and consuming integration are separate review units.
