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

### Code Formatting & Linting

```bash
uv run ruff check .
uv run ruff format --check .
```

---

## Directory & Demo Structure

```
session-03-db-transactions-migrations/
├── app/
│   ├── main.py
│   ├── api/
│   ├── core/
│   ├── db/
│   ├── models/
│   ├── repositories/
│   ├── schemas/
│   └── services/
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
│   └── research-notes.md
├── tests/
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
```

---

## License

Part of the Engineering Excellence Program.