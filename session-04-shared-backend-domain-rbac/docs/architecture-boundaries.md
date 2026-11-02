# Architecture Boundaries & Layer Ownership Guide

## Executive Overview
This document defines the architectural boundaries, folder structure, layer responsibilities, and code ownership rules for **TaskFlow Backend (Session 04: CSR + Shared Package + Domain Workflows + RBAC)**.

To maintain a scalable, testable, and maintainable codebase, every module must adhere strictly to its single layer responsibility. Mixing concerns (e.g., executing SQL queries inside API route handlers, or putting HTTP dependencies inside repository classes) is strictly prohibited.

---

## Repository Directory Structure

```text
session-04-shared-backend-domain-rbac/
├── app/
│   ├── main.py                     # FastAPI application entry point & router registration
│   ├── api/                        # HTTP Controllers & Route Handlers
│   │   ├── dependencies/           # Global FastAPI dependencies (DB session, pagination)
│   │   └── v1/
│   │       └── routes/             # Versioned REST API endpoints (users, projects, tasks, imports)
│   ├── auth/                       # JWT authentication and RBAC policies
│   ├── services/                   # Application Orchestration Services
│   ├── workflows/                  # Task status transition rules
│   ├── repositories/               # Data Access Repositories (PostgreSQL ORM / SQL)
│   ├── models/                     # SQLAlchemy Database Entities
│   ├── schemas/                    # Pydantic DTOs (Request / Response validation)
│   ├── db/                         # Database connection engines (Postgres async session & Motor MongoDB)
│   └── core/                       # Global environment settings & configuration
├── packages/                       # Optional development checkout of the external shared package
│   └── taskflow_shared/            # Independent package checkout; normal installation uses the pinned dependency
│       ├── pyproject.toml          # Standalone package definition
│       └── taskflow_shared/        # Shared cross-cutting modules (config, errors, pagination, logging)
├── tests/                          # Reusable Pytest suite
│   ├── unit/                       # Service & Workflow isolated unit tests
│   ├── integration/                # Full API HTTP integration tests
│   ├── auth/                       # RBAC authorization matrix positive/negative tests
│   └── fixtures/                   # Reusable DB & factory test fixtures
├── docs/                           # Architectural & SLO documentation
│   ├── architecture-boundaries.md  # This layer boundary specification
│   ├── shared-package-notes.md     # Shared package design & usage guidelines
│   ├── workflow-design.md          # Task status transition & domain workflow rules
│   └── rbac-authorization-matrix.md# Role -> Resource -> Allowed/Forbidden matrix
├── demos/                          # Executable and written demo walkthroughs
└── README.md                       # Setup, test, and execution instructions
```

---

## Layer Responsibilities & Ownership Rules

```
 ┌─────────────────────────────────────────────────────────┐
 │                      HTTP Client                        │
 └────────────────────────────┬────────────────────────────┘
                              │ HTTP Request (JSON)
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │ 1. API Route Layer (app/api/)                           │  ◄── Validates request DTOs & serializes JSON responses
 └─────────────┬─────────────────────────────┬─────────────┘
               │ Auth Verification           │ Service Request
               ▼                             ▼
 ┌───────────────────────────┐ ┌───────────────────────────┐
 │ 2. Auth Layer (app/auth/) │ │ 3. Services / Workflows   │  ◄── Enforces business rules & domain workflows
 └───────────────────────────┘ └─────────────┬─────────────┘
                                             │ Repository Method Call
                                             ▼
                               ┌───────────────────────────┐
                               │ 4. Repository Layer       │  ◄── Executes SQLAlchemy queries / Mongo operations
                               └─────────────┬─────────────┘
                                             │ SQL Query
                                             ▼
                               ┌───────────────────────────┐
                               │ 5. Database (PG / Mongo)  │
                               └───────────────────────────┘
```

### 1. API Route Layer (`app/api/`)
* **Responsibility**: HTTP Controller endpoints. Handles HTTP routing, path/query parameter parsing, request DTO validation, status code setting, and response DTO formatting.
* **Allowed Operations**:
  - Receive Pydantic schemas (`TaskCreate`, `TaskAssignRequest`).
  - Will Invoke `app/auth/` dependencies for JWT authentication and role authorization checks.
  - Call application services (`TaskService`) or workflows (`TaskStatusTransitionEngine`).
  - Convert domain entities/tuples to response DTOs using helper functions.
* **Forbidden Anti-Patterns**:
  -  **NO direct SQL or ORM calls**: Never execute `db.execute(select(...))` or `db.commit()` inside a route file.
  -  **NO business logic validation**: Never validate if a project exists or if status transitions are allowed directly in the route function.

---

### 2. Authentication & Authorization Layer (`app/auth/`)
* **Responsibility**: Security guardrail. Handles JWT token decoding, password hashing, user context resolution, and Role-Based Access Control (RBAC) permission checks.
* **Allowed Operations**:
  - Provide FastAPI dependencies (`get_current_user`, `require_role("admin")`).
  - Validate Bearer tokens and verify user active state.
  - Raise `HTTPException(401)` for invalid/missing tokens and `HTTPException(403)` for unauthorized role attempts.
* **Forbidden Anti-Patterns**:
  -  **NO endpoint routing**: Auth layer does not define API endpoints directly (login/signup endpoints live in `app/api/v1/routes/auth.py`).
  -  **NO direct database mutation**: Auth dependencies read user details to verify permissions but do not create/update business domain entities.

---

### 3. Application Services (`app/services/`) & Domain Workflows (`app/workflows/`)
* **Responsibility**: Business logic core.
  - **Services (`app/services/`)**: Orchestrate standard multi-entity operations (e.g. creating a task, linking assignees, initiating notifications).
  - **Workflows (`app/workflows/`)**: Enforce complex state machine rules (e.g. valid task status transitions `TODO` $\rightarrow$ `IN_PROGRESS` $\rightarrow$ `IN_REVIEW` $\rightarrow$ `DONE`).
* **Allowed Operations**:
  - Execute business rule checks (e.g., verifying allowed state transitions or user role eligibility).
  - Invoke repository methods (`TaskRepository.create()`, `UserRepository.get_by_id()`).
  - Perform transaction management across multiple repository operations.
* **Forbidden Anti-Patterns**:
  - **Keep HTTP routing out of services/workflows**: services do not accept HTTP request/response objects or define routes. Existing resource/auth exceptions remain HTTP-compatible adapters backed by the shared error contract; the task-transition workflow raises transport-independent domain errors that routes translate.

---

### 4. Repository Layer (`app/repositories/`)
* **Responsibility**: Data access abstraction. Encapsulates all database query building, filtering, pagination, and persistence operations.
* **Allowed Operations**:
  - Build and execute SQLAlchemy `select()`, `insert()`, `update()`, `delete()` queries.
  - Perform `db.add()`, `db.commit()`, `db.rollback()`, and `db.refresh()`.
  - Return SQLAlchemy model instances or tuples of domain entities.
* **Forbidden Anti-Patterns**:
  -  **NO business logic**: Repositories do not make business decisions (e.g. verifying if a user has permission to change a task).
  -  **NO Pydantic schema dependencies**: Repositories accept primitives (`UUID`, `str`, `dict`) or domain entities—never request/response DTO schemas directly.

---

### 5. Domain Models (`app/models/`) & Schemas (`app/schemas/`)
* **Models (`app/models/`)**: SQLAlchemy declarative ORM mappings (`User`, `Project`, `Task`). Represent database table schemas, foreign key relationships, and indexes.
* **Schemas (`app/schemas/`)**: Pydantic DTOs (`TaskCreate`, `TaskResponse`). Handle API input validation, serialization, and OpenAPI documentation types.

---

### 6. Shared Infrastructure Package (`taskflow_shared`)
* **Responsibility**: Standalone, installable python package for cross-cutting infrastructure concerns shared across microservices or sub-packages.
* **Included Components**:
  - Standard base settings & environment loader (`taskflow_shared.config`).
  - Application exception hierarchy (`taskflow_shared.errors`).
  - Pagination request/response models (`taskflow_shared.pagination`).
  - Request ID tracing & structured logging helpers (`taskflow_shared.logging`).
  - Enums and contract interfaces (`taskflow_shared.enums`, `taskflow_shared.contracts`).
* **Forbidden Anti-Patterns**:
  -  **NO application domain models**: Do not put TaskFlow domain entities (`Task`, `Project`, `User`) inside `taskflow_shared`.

---

##  Before & After Comparison Matrix

| Layer / Concern | Before Refactoring (Session 1-3) | After Refactoring (Session 4 Baseline) |
| :--- | :--- | :--- |
| **Auth Dependencies** | Scattered inside `api/dependencies/deps.py` | Isolated in `app/auth/dependencies.py` |
| **Domain Workflows** | Embedded inside generic service functions | Separated into `app/workflows/` state machine engines |
| **Shared Helpers** | Duplicated across app subfolders |Centralized in the installed external `taskflow_shared` dependency |



## Shared Package Extraction: Before and After

Before integration, settings owned generic environment parsing, resource exceptions repeated error-envelope construction, list schemas repeated pagination fields, and services repeated offset calculations. Request correlation was not registered at the application boundary.

After integration, `taskflow_shared` supplies those common helpers through an immutable external dependency. The app retains database/JWT configuration, resource error codes/messages, HTTP query binding, task-specific schemas/enums, workflow rules, and persistence. `TaskResponse` inherits shared identifier/timestamp contracts. `app.main:application` wraps FastAPI for response tracing while the inner app owns routes and dependency overrides.

The source revision is declared in `pyproject.toml` and locked in `uv.lock`; a nested checkout is optional. Dependencies point from the application to the package, never the reverse. See [package notes](shared-package-notes.md) for the exact module mapping and compatibility decisions.
