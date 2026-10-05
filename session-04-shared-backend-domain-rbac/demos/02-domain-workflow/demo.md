# Demo 02 — Task Status Domain Workflow (todo → in_progress → in_review → done)

## Objective

Prove that task status changes are governed by a **domain workflow** rather than by
HTTP handlers, and that the workflow behaves correctly end to end:

1. **Rules live in the workflow** — the allowed transition graph is defined in
   `app/workflows/task_status_workflow.py` and is the single source of truth.
2. **Valid transitions succeed and persist** — the task status is committed together
   with its audit trail (`task_status_history` + `activity_log`).
3. **Invalid transitions fail consistently** — one error contract
   (`409 INVALID_STATUS_TRANSITION`) for every illegal move.
4. **Failed transitions leave no partial state** — status unchanged, no history row,
   no activity row.
5. **The HTTP layer only translates** — the route delegates to the service, which asks
   the workflow; swapping the workflow's verdict changes the HTTP outcome.

---

## Scenario

TaskFlow tasks move through a linear lifecycle. In a typical sprint:

- An assigned member starts work: `todo → in_progress`.
- A client (or a retry) re-sends the **same** status — this must be a harmless no-op.
- Someone tries to skip ahead (`in_progress → done`) or move work **backwards**
  (`in_progress → todo`) — this must be rejected without corrupting the task or the
  audit trail.
- Work reaches `in_review`, then `done`; a finished task must stay finished.
- An unrelated user tries to change someone else's task status — this must be denied.

The production risk being simulated: *a rejected or failed status change leaving the
task half-updated or the audit trail half-written*, which would make the board and the
history disagree with reality.

---

## Commands / Steps Used

### 1. Interactive workflow demo (used for the transcript below)

```bash
POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_DB=taskflow make demo-workflow
# or directly (same DB env vars are required, as with `make demo-assignment`):
POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_DB=taskflow \
  uv run python -m scripts.demo_domain_workflow
```

The script drives the real HTTP path in-process (ASGI transport, no server needed):
it seeds a user/project/task, walks the workflow, attempts illegal moves, and reads
the database after each step to confirm what was actually persisted.

### 2. Automated regression tests for the same behaviour

```bash
# Pure domain rules (no DB, no HTTP)
uv run pytest -v tests/unit/test_task_status_workflow.py

# Service orchestration + route boundary guards
uv run pytest -v tests/unit/test_task_status_service.py

# API/DB: transitions, audit trail, atomicity, end-to-end HTTP path
uv run pytest -v tests/integration

# Whole suite
POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_DB=taskflow uv run pytest
```

### 3. Equivalent raw API calls (against a running server)

```bash
# valid transition
curl -X PATCH "http://localhost:8000/tasks/<TASK_ID>/status" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: <ASSIGNEE_OR_OWNER_ID>" \
  -d '{"status": "in_progress"}'

# invalid transition (skips a step) -> 409
curl -X PATCH "http://localhost:8000/tasks/<TASK_ID>/status" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: <ASSIGNEE_OR_OWNER_ID>" \
  -d '{"status": "done"}'

# audit trail
curl "http://localhost:8000/tasks/<TASK_ID>/history"
curl "http://localhost:8000/tasks/<TASK_ID>/activity"
```

### 4. Database check

```sql
SELECT status FROM task WHERE id = '<TASK_ID>';
SELECT previous_status, new_status, changed_by_id FROM task_status_history WHERE task_id = '<TASK_ID>';
SELECT action, details FROM activity_log WHERE task_id = '<TASK_ID>';
```

---

## Expected Behavior

| Step | Action | Expected |
| --- | --- | --- |
| 1 | Read the transition graph from the workflow | `TODO→IN_PROGRESS→IN_REVIEW→DONE`; `DONE`/`CANCELLED` terminal |
| 2 | Seed user, project, task | Task starts in `todo` |
| 3 | `PATCH {status: in_progress}` as assignee | `200`; DB `IN_PROGRESS`; 1 history row (`todo→in_progress`, actor); 1 activity row (`task.status_changed`) |
| 4 | Re-send `in_progress` | `200` no-op; **no** extra history/activity rows |
| 5 | `PATCH {status: done}` from `in_progress` | `409 INVALID_STATUS_TRANSITION`; status still `IN_PROGRESS`; no new rows |
| 5 | `PATCH {status: todo}` from `in_progress` | `409 INVALID_STATUS_TRANSITION`; no new rows |
| 6 | Continue to `in_review`, then `done` | Both `200`; final DB status `DONE`; exactly 3 history + 3 activity rows |
| 6 | `PATCH {status: todo}` from `done` | `409` (terminal state frozen) |
| 7 | Unrelated user changes someone else's task | `403 STATUS_CHANGE_FORBIDDEN`; task unchanged; no rows |
| 8 | Request without `X-User-ID` | `401 MISSING_USER_HEADER` |

---

## Actual Findings

Every expectation held:

- The allowed graph printed in Step 1 comes straight from `TaskStatusWorkflow.TRANSITIONS`
  — the route and the service contain no transition table of their own.
- The valid move returned `200`, was committed (`IN_PROGRESS` read back from the
  database by a separate connection), and produced exactly one history row
  (`todo → in_progress`, `changed_by_id` = acting user) plus one activity row
  (`task.status_changed`, `details = {"previous_status": "TODO", "new_status": "IN_PROGRESS"}`).
- Re-sending the same status returned `200` and wrote **nothing** (counts stayed 1/1).
- Both illegal moves (`in_progress → done`, `in_progress → todo`) returned `409` with the
  same code and a message naming both statuses; the task stayed `IN_PROGRESS` and the row
  counts were still 1/1 afterwards — no partial state.
- After completing the workflow, `done → todo` was rejected (`409`); the final status was
  `DONE` with exactly three accepted transitions = three history + three activity rows.
- The unrelated user got `403`, the guarded task stayed `todo`, and **zero** audit rows
  were created for the rejected attempt.
- A request without `X-User-ID` returned `401 MISSING_USER_HEADER`.
- The script exited with `All demo checks passed.`

---

## Evidence

### A. Interactive demo transcript (`make demo-workflow`)

```text
================================================================================
  DEMO 02: TASK STATUS DOMAIN WORKFLOW
================================================================================

[Step 1] Workflow rules are defined in the workflow itself
------------------------------------------------------------------------
  TODO         -> IN_PROGRESS
  IN_PROGRESS  -> IN_REVIEW
  IN_REVIEW    -> DONE
  DONE         -> (terminal)
  CANCELLED    -> (terminal)
  [PASS] todo -> in_progress is legal
  [PASS] todo -> done is illegal

[Step 2] Seed data over HTTP
------------------------------------------------------------------------
  owner    = f83f7a46-0d4f-487a-9f94-f83adb7a38b8
  stranger = f666f3a5-940d-422f-a129-dd4eee3b80b1
  project  = 2607b4cb-18f2-48c7-966a-b666e2609901
  task     = b448f3ad-4cae-4cba-856b-5f07e735c05d
  [PASS] task starts in 'todo'  (todo)

[Step 3] Valid transition: todo -> in_progress
------------------------------------------------------------------------
  HTTP 200  body.status=in_progress
  [PASS] API returns 200
  [PASS] DB status is IN_PROGRESS  (IN_PROGRESS)
  [PASS] exactly 1 history row  (1)
  [PASS] exactly 1 activity row  (1)
  history  : prev=todo new=in_progress by=f83f7a46-0d4f-487a-9f94-f83adb7a38b8
  activity : task.status_changed details={'new_status': 'IN_PROGRESS', 'previous_status': 'TODO'}

[Step 4] Same status again -> idempotent no-op (no new rows)
------------------------------------------------------------------------
  [PASS] API returns 200
  [PASS] no extra history row  (1)
  [PASS] no extra activity row  (1)

[Step 5] Invalid transitions -> 409 with one consistent error
------------------------------------------------------------------------
  in_progress -> done        (skips the review step) HTTP 409 INVALID_STATUS_TRANSITION: Cannot transition task status from 'IN_PROGRESS' to 'DONE'
  [PASS] done rejected with 409
  [PASS] done uses the shared error code
  in_progress -> todo        (moves backwards) HTTP 409 INVALID_STATUS_TRANSITION: Cannot transition task status from 'IN_PROGRESS' to 'TODO'
  [PASS] todo rejected with 409
  [PASS] todo uses the shared error code
  [PASS] status still IN_PROGRESS after rejections  (IN_PROGRESS)
  [PASS] no partial history rows  (1)
  [PASS] no partial activity rows  (1)

[Step 6] Finish the workflow, then try to leave a terminal state
------------------------------------------------------------------------
  -> in_review   HTTP 200
  [PASS] in_review accepted
  -> done        HTTP 200
  [PASS] done accepted
  done -> todo        HTTP 409 INVALID_STATUS_TRANSITION
  [PASS] terminal state is frozen (409)
  [PASS] final DB status is DONE  (DONE)
  [PASS] 3 history rows for 3 accepted moves  (3)
  [PASS] 3 activity rows for 3 accepted moves  (3)

[Step 7] Authorization: unrelated user may not change status
------------------------------------------------------------------------
  HTTP 403 STATUS_CHANGE_FORBIDDEN: Only the assignee, a project owner/manager, or an admin can change a task's status
  [PASS] stranger is forbidden (403)
  [PASS] guarded task unchanged  (TODO)
  [PASS] no audit rows for rejected attempt

[Step 8] Missing identity
------------------------------------------------------------------------
  HTTP 401 MISSING_USER_HEADER
  [PASS] missing X-User-ID is 401

================================================================================
  RESULT
================================================================================
  All demo checks passed.
```

### B. Automated test suites (same behaviour, regression-guarded)

```text
$ uv run pytest tests/unit -q
tests/unit/test_task_status_service.py ........                          [ 34%]
tests/unit/test_task_status_workflow.py ...............                  [100%]
============================== 23 passed in 0.73s ==============================

$ uv run pytest tests/integration -q
tests/integration/test_task_status_api.py .....                          [ 13%]
tests/integration/test_task_status_atomicity.py ......                   [ 29%]
tests/integration/test_task_status_audit_trail.py .....                  [ 43%]
tests/integration/test_task_status_persistence.py .....                  [ 56%]
tests/integration/test_task_status_service_transitions.py .............. [ 94%]
..                                                                       [100%]
============================== 37 passed in 5.08s ==============================
```

### C. Rollback proof (mutation check performed during development)

To confirm that the "no partial state" guarantee depends on the real rollback — and
not merely on the session being closed — the `await db.rollback()` line was temporarily
removed from `TaskService.update_task_status` and the atomicity suite re-run:

```text
$ uv run pytest tests/integration/test_task_status_atomicity.py -q
        # The service explicitly rolled the failed transaction back
>       assert rollback_calls == [True]
========================= 1 failed, 5 passed in 1.89s ==========================
```

The test failed exactly as intended (the rollback spy observed no rollback call), and
passed again once the line was restored — see
`test_flush_then_failure_proves_rollback_of_written_rows`, which flushes the real
`UPDATE`/`INSERT`s to PostgreSQL, snapshot-asserts that the partial state existed inside
the transaction, and then proves the rollback removed it.

---

## What We Learned

- **Business rules belong in the domain layer.** Putting the transition graph in
  `app/workflows/` made it possible to unit-test the rules with zero database or HTTP
  setup, and it kept the API route down to a service call plus a DTO mapping.
- **One error contract is worth the extra translation step.** Rejections come from the
  workflow as a plain `InvalidTransitionError`; the service maps it to
  `409 INVALID_STATUS_TRANSITION`. Every rejection path (skip, backwards, terminal) is
  therefore indistinguishable to clients, which makes error handling predictable.
- **Idempotency needs an explicit decision.** Re-sending the same status is *not* an
  invalid transition; treating it as a silent no-op avoids spurious 409s for retrying
  clients, but it means the audit trail intentionally has no "nothing changed" rows.
- **Proving rollback requires writing first.** Tests that inject a failure before any
  SQL is sent pass even when rollback is missing, because closing the session discards
  the transaction. Only flushing real rows, snapshotting them, and then asserting the
  rollback removed them (plus a spy that the rollback was called) actually proves the
  behaviour.
- **Actor attribution is part of the audit data.** Recording `changed_by_id` /
  `actor_id` from the request identity — not from a payload field — is what makes the
  history answer "who did this?" reliably.

---

## Open Questions

- **Authentication:** `X-User-ID` is a test stand-in for identity. When JWT auth lands,
  the header should be replaced by the token subject and the `401` codes kept as-is.
- **Backwards moves:** should `in_review → in_progress` (send back for changes) be
  allowed? Today it is rejected; adding it is a product decision plus a graph change.
- **Re-opening:** should `done → todo` ever be permitted for reopened tickets, and who
  may do it?
- **`CANCELLED`:** the status exists in the database enum but is unreachable through the
  API. Should it become a real transition (e.g. from `todo`/`in_progress`) and who may
  set it?
- **Assignment endpoint consistency:** `POST /tasks/{id}/assign` validates status
  changes through the same workflow but still takes its actor from the request payload;
  should it use the header identity too?
- **Read-side authorization:** the optional tenant rule ("a user cannot read/update
  resources belonging to another workspace") is enforced for status changes only —
  `GET /tasks` remains open.



