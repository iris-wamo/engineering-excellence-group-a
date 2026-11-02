# Shared package dependency

TaskFlow installs the independent [taskflow-shared package](https://github.com/husnainmazhar45/taskflow-shared) from the exact commit declared in the session's `pyproject.toml`. Its source archive is locked in `uv.lock`; no nested checkout is needed for application setup, tests, or Docker builds.

```bash
uv sync --locked
```

An optional development clone can live in `packages/taskflow_shared/`. That directory is ignored by the application repository so package implementation changes are reviewed in their own repository rather than accidentally vendored here. Installing that clone manually does not change the application's declared dependency; keep experiments in a separate environment.

The pinned package commit is `82b2360ff5958b9a5f45d27d2e939ed8c73a1f3e`, corresponding to the [shared-package implementation PR](https://github.com/husnainmazhar45/taskflow-shared/pull/1). Update both the source declaration and lockfile together when adopting another package revision.
