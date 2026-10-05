# Session 4 — Task Status Workflow Design

## Objective

Document the domain workflow that governs task status changes in TaskFlow: the
allowed transition graph, who may trigger a change, where the rules live, how the
audit trail is produced, and how transaction/rollback behaviour guarantees that a
failed transition leaves no partial state.

The workflow exists so that "can this task move from A to B?" is answered in exactly
one place, independent of HTTP, persistence, and authorization concerns.

## What the workflow is

The **task status transition engine**: the single source of truth for which status
moves are legal. It is a pure domain component — no FastAPI, no database, no
repositories — so it can be unit tested in isolation.

```text
HTTP request
   ↓
API route          (request/response + identity)
   ↓
Service            (authorization, orchestration, transaction boundary, error translation)
   ↓
Workflow           (business rules: is this transition legal?)
   ↓
Repository / DB    (staging, reads, writes)
```

## Where the workflow lives

| Concern | Location |
| --- | --- |
| Workflow (rules + domain error) | `app/workflows/task_status_workflow.py` |
| Package docstring | `app/workflows/__init__.py` |
| Status enum (contract shared with the DB) | `app/models/task.py` (`TaskStatus`) |
| Service orchestration | `app/services/task_service.py` (`TaskService`) |
| API route | `app/api/v1/routes/tasks.py` (`PATCH /tasks/{task_id}/status`) |
| HTTP error shapes | `app/core/exceptions.py` |
| API-facing status values | `app/schemas/task.py` (`TaskStatusValue`) |

Workflow API surface:

| Member | Purpose |
| --- | --- |
| `TaskStatusWorkflow.TRANSITIONS` | The transition graph (single source of truth) |
| `TaskStatusWorkflow.START` / `.FINAL` | `TODO` / `DONE` |
| `TaskStatusWorkflow.allowed_next(status)` | Legal next statuses |
| `TaskStatusWorkflow.is_terminal(status)` | True when no move can leave the status |
| `TaskStatusWorkflow.can_transition(current, target)` | Boolean verdict |
| `TaskStatusWorkflow.validate(current, target)` | Raises `InvalidTransitionError` when illegal |
| `InvalidTransitionError` | Domain error carrying `current`, `target`, `allowed` |

## Allowed transitions

The lifecycle is linear: `todo → in_progress → review → done`.

| From (DB enum) | Allowed next | Notes |
| --- | --- | --- |
| `TODO` | `IN_PROGRESS` | Entry status for new tasks |
| `IN_PROGRESS` | `IN_REVIEW` | |
| `IN_REVIEW` | `DONE` | |
| `DONE` | *(none)* | Terminal |
| `CANCELLED` | *(none)* | Terminal, and currently not reachable via the API |

REST/API spellings (lowercase) map onto the DB enum values:

| API value | DB enum |
| --- | --- |
| `todo` | `TODO` |
| `in_progress` | `IN_PROGRESS` |
| `in_review` | `IN_REVIEW` |
| `done` | `DONE` |

## Invalid transitions

Every request that does not appear as an edge in `TRANSITIONS` is rejected with a
consistent `409` domain error:

| Category | Examples |
| --- | --- |
| Skipping a step | `todo → in_review`, `todo → done`, `in_progress → done` |
| Moving backwards | `in_progress → todo`, `in_review → in_progress`, `in_review → todo` |
| Leaving a terminal state | `done → todo`, `done → in_progress`, `done → in_review` |
| Same status | `todo → todo` — treated as a successful no-op, **not** an error |

Rejection returns:

```json
{
  "detail": {
    "error": {
      "code": "INVALID_STATUS_TRANSITION",
      "message": "Cannot transition task status from 'TODO' to 'DONE'"
    }
  }
}
```

## Business rules

1. **Transition graph** — only the edges in `TaskStatusWorkflow.TRANSITIONS` are legal;
   `DONE` and `CANCELLED` are terminal.
2. **Identity is required** — the acting user is resolved from the `X-User-ID` header;
   missing or unknown identity → `401`.
3. **Authorization** — a status change is allowed only for:
   - a global `ADMIN`, or
   - the task's assignee, or
   - the project owner, or
   - a project member with role `OWNER` or `MANAGER`.
   Anyone else → `403 STATUS_CHANGE_FORBIDDEN`. (Session 4 rule: *members can update
   status only for tasks assigned to them*; owners/managers/admins are the documented
   escalation paths so unassigned tasks cannot get stuck.)
4. **Task must exist** — unknown task id → `404`.
5. **Idempotent no-op** — re-sending the current status returns `200` without writing
   history or activity.
6. **Audit trail is mandatory** — every successful change writes one status-history row
   and one activity-log row in the same transaction.
7. **Atomicity** — status update, history, and activity commit together or not at all.
8. **One rule set for every path** — `PATCH /tasks/{id}/status` and the optional
   `new_status` of `POST /tasks/{id}/assign` both go through the same workflow, so the
   graph cannot be bypassed.

## Responsibilities by layer

### Workflow (`app/workflows/task_status_workflow.py`)

Owns:

- the allowed transition graph;
- the verdict for a proposed transition (`can_transition` / `validate`);
- terminal-state knowledge (`is_terminal`, `allowed_next`);
- the **domain error** raised on rejection (`InvalidTransitionError`), including the
  structured `current` / `target` / `allowed` fields and the canonical message.

Does **not** own:

- HTTP status codes, JSON error envelopes, FastAPI imports;
- database access, repositories, sessions, or transactions;
- authorization/identity;
- audit-trail persistence.

### Service (`TaskService.update_task_status`)

Owns:

- retrieving the task and raising `404` when missing;
- enforcing authorization (`403`);
- deciding the idempotent no-op case (same status → return early);
- **invoking the workflow** to validate the transition;
- translating `InvalidTransitionError` into the HTTP `409` error;
- orchestrating the transaction: staging all writes, `flush`, one `commit`,
  `rollback` on any failure;
- recording the actor on the history/activity rows.

The decisive ordering inside the service:

```text
retrieve task (404)
  → authorize (403)
  → same status? return early (200, no writes)
  → workflow.validate()  → InvalidTransitionError ⇒ 409
  → stage status update + history + activity
  → flush → commit   (except: rollback, re-raise)
```

### API (`PATCH /tasks/{id}/status`)

Owns:

- the route definition, request schema (`TaskStatusUpdate`) and response DTO
  (`TaskResponse`);
- resolving the acting user through the `CurrentUserDep` dependency
  (`X-User-ID` → `User`, `401` when missing/unknown);
- calling the service and mapping the result into the response.

Does **not** own: transition rules, authorization rules, or error handling. The route
body contains only a call to `TaskService.update_task_status(...)` and
`to_task_response(...)` — verified by
`tests/unit/test_task_status_service.py::test_status_route_is_request_response_only`
and `::test_route_contains_no_transition_business_rules`.

## How history/activity is generated

For every **successful** transition the service stages, in the same transaction:

**1. `task_status_history` row** (`TaskRepository.add_status_history`)

| Column | Value |
| --- | --- |
| `task_id` | the task that changed |
| `previous_status` | status read before the change (e.g. `TODO`) |
| `new_status` | status after the change (e.g. `IN_PROGRESS`) |
| `changed_by_id` | the acting user (from `X-User-ID`) |
| `created_at` | single timestamp shared with the activity row |

**2. `activity_log` row** (`ActivityLogRepository.stage_create`)

| Column | Value |
| --- | --- |
| `task_id` | the task that changed |
| `actor_id` | the acting user |
| `action` | `"task.status_changed"` |
| `details` | `{"previous_status": "TODO", "new_status": "IN_PROGRESS"}` (DB enum values) |
| `created_at` | same timestamp as the history row |

Rules applied:

- the rows describe the transition that **actually happened** — the values are taken
  from the status read before the write and the target status, not recomputed later;
- no rows are written for no-op requests or rejected transitions;
- the assignment flow additionally writes `task.assigned` activity plus the same status
  history when it changes status in the same transaction;
- the trail is readable via `GET /tasks/{id}/history` (`{"assignments": [...], "statuses": [...]}`)
  and `GET /tasks/{id}/activity`, both newest-first.

## Transaction and rollback behaviour

The status change is one transaction boundary (the Session 3 pattern: repositories
stage, the service commits):

```python
try:
    TaskRepository.stage_update_status(db, task, target_status)   # task UPDATE
    TaskRepository.add_status_history(...)                        # history INSERT
    ActivityLogRepository.stage_create(...)                       # activity INSERT

    await db.flush()     # surface DB-level errors before COMMIT
    await db.commit()    # all three succeeded
except Exception:
    await db.rollback()  # any failure undoes all of it
    raise
```

Guarantees and how they are proven:

| Guarantee | Evidence |
| --- | --- |
| Successful transition is committed and visible to other connections | `tests/integration/test_task_status_persistence.py` |
| History/activity mirror the real transition | `tests/integration/test_task_status_audit_trail.py` |
| Failure before/at flush/at commit rolls everything back | `tests/integration/test_task_status_atomicity.py` |
| **Rollback undoes already-written rows** | `test_flush_then_failure_proves_rollback_of_written_rows` — flushes the real UPDATE/INSERTs, snapshot-asserts the partial state existed, then proves the rollback removed it and that `Session.rollback()` was called exactly once |
| Rejected transitions leave zero partial state | `tests/integration/test_task_status_service_transitions.py` |
| Service validates before writing | `tests/unit/test_task_status_service.py` (call-order spy) |

Because validation happens **before** any write is staged, an invalid transition cannot
even reach the database; because all writes share one session transaction, a failure
mid-way cannot leave a partially updated task or orphan audit rows.

## Error contract

All failures share one envelope: `{"detail": {"error": {"code": ..., "message": ...}}}`.

| HTTP | Code | Decided by |
| --- | --- | --- |
| `401` | `MISSING_USER_HEADER` | API dependency (no `X-User-ID`) |
| `401` | `CURRENT_USER_NOT_FOUND` | API dependency (unknown user id) |
| `403` | `STATUS_CHANGE_FORBIDDEN` | service authorization rule |
| `404` | `TASK_NOT_FOUND` | service lookup |
| `409` | `INVALID_STATUS_TRANSITION` | workflow (translated by the service) |

## Design decisions and tradeoffs

| Decision | Rationale | Tradeoff |
| --- | --- | --- |
| Rules live in a dedicated `app/workflows/` module | One place to change the lifecycle; unit-testable without DB/HTTP | One more layer to navigate |
| Workflow raises a plain domain error (`InvalidTransitionError`), service translates to `409` | Keeps FastAPI/HTTP out of the domain layer | Error mapping knowledge sits in the service |
| Service validates **before** staging any write | A rejected transition can never leave partial state | Slightly earlier failure than a DB constraint would give |
| Linear graph with no backwards moves and no re-open | Simple, predictable flow; matches the Session 4 rule | Re-opening a task or sending it back for changes needs a new edge and a migration of expectations |
| `CANCELLED` exists in the DB enum but is unreachable via the API and terminal | Preserves the schema/enum for future use without opening an unfinished path | Documented dead-end: changing it needs an explicit workflow decision |
| Same status returns `200` (no-op) instead of an error | Makes the endpoint idempotent-friendly for clients/retries | Callers do not get feedback that "nothing happened" beyond the unchanged status |
| DB enum values are uppercase, REST values lowercase, mapped in one place (`_STATUS_TO_MODEL` / `_STATUS_TO_API`) | Keeps existing migrations/`taskstatus` enum untouched while exposing clean REST values | Two spellings for the same concept; the map must be kept in sync with `TaskStatusValue` |
| Activity `details` stores DB enum values (`"IN_PROGRESS"`) while the history API returns REST values (`"in_progress"`) | `details` is free-form JSONB written at change time; the DTO layer owns the REST spelling | Slightly different formatting between the two endpoints |
| Authorization is service-level, not part of the workflow | Workflow stays a pure "is this move legal?" component | "Who can do what" and "what is allowed" must be read in two files |
| `X-User-ID` header is the identity source | No JWT auth exists in this session yet; keeps the contract explicit and testable | Temporary stand-in: it is client-asserted and must be replaced by real authentication (session deliverable) before production |
| `POST /tasks/{id}/assign` reuses the same workflow validation | The status graph cannot be bypassed through the assignment endpoint | `assign` still takes its actor from the payload rather than the header (see open questions) |

## Testing map

| Test file | Level | Covers |
| --- | --- | --- |
| `tests/unit/test_task_status_workflow.py` | unit (domain) | Allowed transitions, every invalid category, terminal states, error structure, no HTTP leakage |
| `tests/unit/test_task_status_service.py` | unit (service) | Retrieve → authorize → validate → write ordering, no-op, error translation, route boundary guards, Session 3 transaction pattern |
| `tests/integration/test_task_status_service_transitions.py` | service + real DB | Positive transitions, full chain, no-op, all invalid transitions, untouched audit trail, single error contract |
| `tests/integration/test_task_status_persistence.py` | API + DB | Commit visibility from a fresh connection |
| `tests/integration/test_task_status_audit_trail.py` | API + DB | History/activity correctness, actor attribution, audit endpoints |
| `tests/integration/test_task_status_atomicity.py` | API + DB | Rollback at every failure point, including the flush-then-fail rollback proof |
| `tests/integration/test_task_status_api.py` | API + DB | End-to-end HTTP path, error contract, proof that the route defers to the workflow |

## Open questions / future work

- Replace the `X-User-ID` stand-in with real JWT authentication (signup/login) and
  derive the actor from the token; `401` codes stay the same.
- Decide whether `assign_task` should take the actor from the header instead of the
  request payload, so all actor attribution has a single source.
- Decide whether the workflow should allow sending a task back
  (`in_review → in_progress`) or re-opening a finished task; that is a product decision
  plus a transition-graph change.
- Decide whether `CANCELLED` becomes reachable and who may set it.
- Read endpoints (`GET /tasks`, `GET /tasks/{id}`) are still unauthenticated; the
  optional tenant rule ("a user cannot read/update resources belonging to another
  workspace") is enforced only for status changes today.
- Consider a shared, reusable domain-error base if more workflows are added.


