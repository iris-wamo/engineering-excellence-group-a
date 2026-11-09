A FastAPI backend demonstrating clean REST API design, validation, consistent response models, pagination, filtering, and maintainable architecture.

This repo is organized as a series of engineering exercises, one directory per session, each building on the last.

## Sessions

### Session 01 — API Design (`session-01-api-design/`)

Build the base version of TaskFlow — a team work-management backend — with clean API contracts. This session established:

* A layered architecture (endpoint → service → repository → model) with a shared error envelope for every error response.
* SQLAlchemy models and Alembic migrations for the core data model: user, project, task, and the project_user membership join.

See `session-01-api-design/README.md` for setup instructions.

### Session 02 — Dockerized Development & Code Review Standards (`session-02-dockerized-development-and-code-review-standards/`)

Take the Session 01 API and harden it for team development. This session covers:

* Package management with `uv`, with a committed lockfile for reproducible installs.
* Code-quality tooling: ruff, mypy, pytest, and pre-commit hooks running all of the above before code reaches review.
* Dockerizing the application with `api`, `postgres`, and `test` services via Compose, plus a Makefile for common commands.
* An entrypoint script that runs migrations before the API starts, so the container can't come up against a stale schema.

See `session-02-dockerized-development-and-code-review-standards/README.md` for setup instructions.

### Session 05 — Async, Redis & Celery (`session-05-async-redis-celery/`)

Builds on Session 4. S5-01 adds a healthchecked Redis service, persistent named
volume, and a shared async Redis client managed by FastAPI's lifespan.
See [Session 5 setup](session-05-async-redis-celery/README.md) and the
[Redis walkthrough](session-05-async-redis-celery/docs/s5-01-redis.md).
