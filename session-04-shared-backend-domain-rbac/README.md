# TaskFlow API - Session 03: Database Transactions & Migrations

Engineering Excellence Program — TaskFlow Backend MVP focusing on database correctness, transactions, schema migrations, and query performance.

## Overview

Session 3 shifts focus deep into the database layer of the TaskFlow application to address production-level database concerns:
- **Transaction-Safe Task Operations**: Atomic single-transaction boundary covering task updates, assignment history, status history, activity logging, and notifications with full rollback safety.
- **Alembic Migrations**: Safe, reproducible database migrations and schema evolution.
- **Query Optimization**: EXPLAIN ANALYZE inspection and composite indexing to eliminate slow queries.
- **ORM Query Efficiency**: Eliminating N+1 queries and controlling lazy vs eager loading behavior.
- **Concurrency & Locking**: Understanding row-level locks, transaction isolation, and deadlock prevention.
- **MongoDB Raw Payload Store**: Document storage for raw import payloads and traceability.

---

## Prerequisites

- Python 3.12 or higher
- Docker and Docker Compose
- PostgreSQL database (or via Docker Compose)
- MongoDB instance (for raw task import payloads)
- `uv` package manager

---

## Quick Start

### 1. Environment Setup

Navigate to the directory:
```bash
cd session-03-db-transactions-migrations
```

Install dependencies using `uv`:
```bash
uv sync
```

Copy the example environment file:
```bash
cp .env.example .env
```

Update `.env` with your PostgreSQL and MongoDB credentials:
```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=taskflow

MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=taskflow_imports

APP_ENV=development
```

### 2. Run Database Migrations

Apply the latest Alembic migrations:
```bash
uv run alembic upgrade head
```

### 3. Start the Application

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Access API Documentation:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## Authentication & RBAC (Session 4)

Every endpoint except `POST /auth/signup`, `POST /auth/login` and `GET /health`
requires a JWT bearer token. Roles are `admin`, `manager` and `member`; see
[docs/rbac-authorization-matrix.md](docs/rbac-authorization-matrix.md) for who can
do what.

1. Add the JWT settings to `.env` (see `.env.example`). `JWT_SECRET_KEY` is required,
   at least 32 characters:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
2. Apply migrations (`make migrate`). Migration `c4a7e2f19b3d` lowercases existing
   roles and makes every project owner that project's manager.
3. Create the first admin. Signup always creates members:
   ```bash
   make create-admin            # prompts for email, username, name, password
   ```
4. Optional: load demo data. 3 projects are created by the admin and 1 by a manager,
   with managers and members (all with password `Password123!`):
   ```bash
   make seed-rbac
   ```
5. Log in and call the API:
   ```bash
   TOKEN=$(curl -s -X POST localhost:8000/auth/login \
     -d "username=alice&password=Password123!" | jq -r .access_token)
   curl localhost:8000/projects -H "Authorization: Bearer $TOKEN"
   ```
   In Swagger, use **Authorize** with a username (or email) and password.

---

## Session 3 Features & Architecture

### Database Models (`app/models/`)

- `User`: User management & credentials.
- `Project`: Project management with database-level `slug` unique constraint.
- `ProjectMember`: Many-to-many user membership per project.
- `Task`: Task entity with priority, status, and assignment.
- `TaskAssignmentHistory`: Tracks previous & new assignee upon assignment changes.
- `TaskStatusHistory`: Audit trail of task status transitions.
- `ActivityLog`: Comprehensive log of task-related actions with `JSONB` details.
- `Notification`: In-app notification records for assignees and project members.

---

## Verification & Testing

### Running Tests

```bash
POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_DB=taskflow uv run pytest
```

Tests run against `TEST_DATABASE_URL`, which must be migrated to head first
(`DATABASE_URL=<test db url> uv run alembic upgrade head`). `tests/conftest.py`
supplies a test-only `JWT_SECRET_KEY` when none is set. The RBAC suite lives in
`tests/auth/`.

### Code Formatting & Linting

```bash
uv run ruff check .
uv run ruff format --check .
```

---

## Directory & Demo Structure

```
session-04-shared-backend-domain-rbac/
├── app/
│   ├── main.py
│   ├── api/
│   ├── core/
│   ├── db/
│   ├── models/
│   ├── repositories/
│   ├── schemas/
│   ├── services/
│   └── workflows/
├── alembic/
│   └── versions/
├── demos/
│   ├── 01-transaction-safe-assignment/
│   ├── 02-alembic-migrations/
│   ├── 03-index-explain-analyze/
│   ├── 04-orm-query-breakdown/
│   ├── 05-locks-and-deadlocks/
│   └── 06-mongo-raw-import/
├── docs/
│   ├── slo-and-deliverables.md
│   ├── migration-safety-checklist.md
│   ├── db-ide-findings.md
│   ├── issue-11-schema-design.md
│   ├── research-notes.md
│   ├── workflow-design.md
│   └── code-walkthrough.md
├── scripts/
│   ├── demo_transaction_safe_assignment.py
│   └── demo_domain_workflow.py
├── tests/
│   ├── unit/                     # domain workflow + service boundary tests
│   ├── integration/              # status transition API/DB + audit/atomicity
│   └── test_*.py                 # API and database suites
└── README.md
```

---

## Common Make Commands

```bash
make install       # Install dependencies
make lint          # Check lint issues
make format        # Format code using Ruff
make test          # Run test suite
make run           # Start development server
make migrate       # Run database migrations
make demo-assignment  # Run the transaction-safe assignment demo
make demo-workflow    # Run the task status workflow demo
```

---

## License

Part of the Engineering Excellence Program.