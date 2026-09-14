# Demo 01 — Transaction-Safe Task Assignment & DB Constraints

## Loom Video

*Loom Video Link*: `[Paste Loom link here]`

---

## Objective

Prove that complex multi-table business operations (task assignment, status change, assignment history, status history, activity audit logging, and notification creation) execute within a **single atomic transaction boundary** (ACID compliance), ensuring:
1. **Atomicity & Consistency**: All 5 related records commit together on success.
2. **Zero Partial Writes**: If any failure occurs mid-flight (e.g., downstream notification error, constraint violation, or unhandled exception), the entire operation rolls back cleanly, leaving database state unmodified.
3. **Audit Trail Integrity**: Previous and new assignees are preserved accurately across task lifecycle changes.
4. **Database-Level Defense**: Database constraints (unique email, unique username, unique project slug, foreign keys, not-null constraints) prevent data corruption regardless of API-level validation bypasses.

---

## Scenario

In a real production environment, assigning a task triggers multiple side-effects:
1. Updating `task.assigned_to` and `task.status`.
2. Inserting an audit row into `task_assignment_history` (capturing previous -> new assignee).
3. Inserting an audit row into `task_status_history` (capturing previous -> new status).
4. Writing an audit log entry to `activity_log` with JSON metadata (actor, action, timestamps, notes).
5. Enqueueing a database record in `notification` to notify the assignee.

### The Production Failure Case We Simulated:
A developer updates `task.assigned_to` and writes to history, but the notification dispatch or downstream activity logger throws an unexpected error (e.g. timeout, malformed payload, or DB constraint). Without an explicit database transaction boundary, the database enters a **corrupted partial write state**:
- The task is marked as assigned.
- The history row is committed.
- But the user never received the notification and audit logs are missing.
- When retried, duplicate history or phantom states emerge.

We simulated an unhandled exception at Step 5 (Notification dispatch) and demonstrated that PostgreSQL automatically aborts all preceding changes, leaving the database state 100% clean.

---

## Commands / Steps Used

### 1. Interactive Demo Execution Command
```bash
make demo-assignment
# Or directly via uv:
uv run python -m scripts.demo_transaction_safe_assignment
```

### 2. Automated Regression & Rollback Tests
```bash
uv run pytest -v tests/test_task_assignment.py tests/test_constraints.py
```

### 3. API Execution (cURL / HTTP Requests)

#### Successful Task Assignment:
```bash
curl -X POST "http://localhost:8000/tasks/83799123-3a80-40d0-843f-27dd43d5829d/assign" \
  -H "Content-Type: application/json" \
  -d '{
    "assignee_id": "549bc9fe-8d56-4038-ab3e-44469ee810f3",
    "assigned_by_id": "9402b714-c8f3-4038-943f-f262c9c77cb2",
    "new_status": "in_progress",
    "comment": "Sprint 3 high-priority backend deliverable"
  }'
```

#### Simulated Failure & Rollback Test (API Level):
```bash
curl -X POST "http://localhost:8000/tasks/83799123-3a80-40d0-843f-27dd43d5829d/assign?simulate_failure=true&simulate_failure_step=5" \
  -H "Content-Type: application/json" \
  -d '{
    "assignee_id": "9d716735-2396-40eb-be2d-12589b936c42",
    "assigned_by_id": "9402b714-c8f3-4038-943f-f262c9c77cb2",
    "new_status": "in_progress",
    "comment": "Testing rollback guarantee"
  }'
```

### 4. Verification SQL Queries in PostgreSQL / DBeaver
```sql
-- 1. Check Task State
SELECT id, title, status, assigned_to, assigned_by, updated_at FROM task WHERE id = '83799123-3a80-40d0-843f-27dd43d5829d';

-- 2. Check Assignment History Trail
SELECT id, task_id, previous_assignee_id, new_assignee_id, assigned_by_id, created_at FROM task_assignment_history WHERE task_id = '83799123-3a80-40d0-843f-27dd43d5829d' ORDER BY created_at ASC;

-- 3. Check Status Transition History
SELECT id, task_id, previous_status, new_status, changed_by_id, created_at FROM task_status_history WHERE task_id = '83799123-3a80-40d0-843f-27dd43d5829d';

-- 4. Check Activity Audit Log
SELECT id, task_id, actor_id, action, details, created_at FROM activity_log WHERE task_id = '83799123-3a80-40d0-843f-27dd43d5829d';

-- 5. Check Notification Record
SELECT id, recipient_id, task_id, type, message, is_read, created_at FROM notification WHERE task_id = '83799123-3a80-40d0-843f-27dd43d5829d';
```

---

## Expected Behavior

1. **Commit Path**:
   - `task.assigned_to` is updated to the new user UUID.
   - 1 new row in `task_assignment_history` with `previous_assignee_id` (or `NULL` if first assignment) and `new_assignee_id`.
   - 1 new row in `task_status_history` reflecting the status transition (e.g. `TODO` -> `IN_PROGRESS`).
   - 1 new row in `activity_log` with action `"task.assigned"` and actor metadata.
   - 1 new row in `notification` addressed to the assignee.
2. **Failure & Rollback Path**:
   - HTTP 500 error returned (`SIMULATED_TRANSACTION_FAILURE`).
   - `task.assigned_to` remains unchanged in the database.
   - 0 rows inserted in `task_assignment_history`, `task_status_history`, `activity_log`, and `notification`.
3. **Constraint Enforcement**:
   - Attempting to insert duplicate `user.email`, `user.username`, or `project.slug` raises a database `IntegrityError` (PostgreSQL `23505 unique_violation`).
   - Attempting to link a foreign key to a non-existent parent raises an `IntegrityError` (PostgreSQL `23503 foreign_key_violation`).

---

## Actual Findings

Execution of `make demo-assignment` and pytest test suite confirmed 100% adherence to ACID properties:

1. **Success Scenario**: All 5 records were committed together in a single transaction.
2. **Rollback Scenario**: Injected failure at step 5 resulted in an immediate transaction rollback. Direct database inspection showed row count deltas of **+0** across all related tables.
3. **Re-assignment Lineage**: Lineage was preserved across multiple re-assignments, with `previous_assignee_id` accurately reflecting previous owners.
4. **Constraint Enforcement**: PostgreSQL successfully rejected duplicate project slugs, duplicate user emails, and orphaned foreign keys at the storage layer.

---

## Evidence

### Terminal Output from Demo Script (`make demo-assignment`):

```text
================================================================================
  DEMO 01: TRANSACTION-SAFE TASK ASSIGNMENT & DB CONSTRAINTS
================================================================================
Connecting to Database: taskflow at localhost:5432

[Step 1] Setting up Demo Data (Lead, Backend Dev, Frontend Dev, Project, Task)
------------------------------------------------------------
Created Lead User    : Faiza Lead (2d1b96) (9402b714-c8f3-4038-943f-f262c9c77cb2)
Created Backend Dev  : Khubaib Backend (2d1b96) (549bc9fe-8d56-4038-ab3e-44469ee810f3)
Created Frontend Dev : Huzaifa Frontend (2d1b96) (9d716735-2396-40eb-be2d-12589b936c42)
Created Project      : Core Platform Refactor [slug: core-platform-2d1b96]
Created Initial Task : 'Implement Transaction Boundary for Task Assignment' | Status: TODO | Assignee: None

[Step 2] SCENARIO 1: Executing 5-Step Transaction-Safe Assignment Flow
------------------------------------------------------------
>> Beginning single atomic database transaction...
   [1/5] Task updated: assigned_to=Backend Dev, status=IN_PROGRESS
   [2/5] TaskAssignmentHistory staged: previous=None -> new=Backend Dev
   [3/5] TaskStatusHistory staged: TODO -> IN_PROGRESS
   [4/5] ActivityLog staged: actor=Lead User, action='task.assigned'
   [5/5] Notification staged: recipient=Backend Dev, unread=True
>> Transaction COMMITTED successfully! All 5 records persisted together.

--- Direct Database Inspection (Post-Commit) ---
Task Table               : ID=83799123-3a80-40d0-843f-27dd43d5829d | Assignee=549bc9fe-8d56-4038-ab3e-44469ee810f3 | Status=IN_PROGRESS
TaskAssignmentHistory (x1) : ID=0af011b9-5dc0-4a46-bebb-dd910fed5689 | New Assignee=549bc9fe-8d56-4038-ab3e-44469ee810f3
TaskStatusHistory (x1)     : ID=6600f5e7-2249-4d58-aa58-8e9aaac1b026 | TODO -> IN_PROGRESS
ActivityLog (x1)           : Action='task.assigned' | Details={'previous_assignee_id': None, 'new_assignee_id': '549bc9fe-8d56-4038-ab3e-44469ee810f3', 'assigned_by_name': 'Faiza Lead (2d1b96)', 'new_assignee_name': 'Khubaib Backend (2d1b96)', 'comment': 'Sprint 3 high-priority backend deliverable'}
Notification (x1)          : Message='You have been assigned to task 'Implement Transaction Boundary for Task Assignment' by Faiza Lead (2d1b96).' | Read=False

[Step 3] SCENARIO 2: Simulated Failure at Step 5 (Notification Failure) & Rollback Proof
------------------------------------------------------------
>> Attempting to reassign task to Frontend Dev, simulating an exception at Step 5...
   [1/5] Staged task assignee change -> Frontend Dev
   [2/5] Staged TaskAssignmentHistory (Backend -> Frontend)
   [3/5] Staged ActivityLog
   [4/5] Simulating network/database failure during Notification dispatch...

   [!] Caught simulated exception: CRITICAL: Notification dispatch failed due to downstream timeout!
   [!] Executing 'await db.rollback()' to revert all uncommitted changes...
   [!] Rollback complete.

--- Rollback Proof Verification ---
Task Assignee in DB     : 549bc9fe-8d56-4038-ab3e-44469ee810f3 (Expected: 549bc9fe-8d56-4038-ab3e-44469ee810f3 [Backend Dev]) -> VERIFIED MATCH
Assignment History Rows : Before=1 | After=1 (Delta=+0) -> ZERO PARTIAL WRITES
Activity Log Rows       : Before=1 | After=1 (Delta=+0) -> ZERO PARTIAL WRITES
Notification Rows       : Before=1 | After=1 (Delta=+0) -> ZERO PARTIAL WRITES

[Step 4] SCENARIO 3: Successful Re-assignment Flow (Backend Dev -> Frontend Dev)
------------------------------------------------------------
>> Re-assignment transaction committed successfully!

Task Assignment Lineage History (2 entries):
  1. [Prev: None (Unassigned)] -> [New: User 549bc9fe-8d56-4038-ab3e-44469ee810f3] by [Assigner: User 9402b714-c8f3-4038-943f-f262c9c77cb2] at 2026-09-03 08:38:56.978116
  2. [Prev: User 549bc9fe-8d56-4038-ab3e-44469ee810f3] -> [New: User 9d716735-2396-40eb-be2d-12589b936c42] by [Assigner: User 9402b714-c8f3-4038-943f-f262c9c77cb2] at 2026-09-03 08:38:57.007183

[Step 5] SCENARIO 4: Database-Level Constraints Enforcement
------------------------------------------------------------
4a. Testing UNIQUE constraint on user.email...
   SUCCESS: Postgres rejected duplicate email with IntegrityError (UNIQUE constraint)

4b. Testing UNIQUE constraint on project.slug...
   SUCCESS: Postgres rejected duplicate slug with IntegrityError (UNIQUE constraint)

4c. Testing FOREIGN KEY constraint on notification.recipient_id...
   SUCCESS: Postgres rejected non-existent foreign key with IntegrityError (FOREIGN KEY constraint)

================================================================================
  ALL DEMO SCENARIOS COMPLETED SUCCESSFULLY!
================================================================================
```

### Pytest Verification Results (`uv run pytest -v`):
```text
tests/test_constraints.py::test_db_constraint_unique_user_email PASSED   [  3%]
tests/test_constraints.py::test_db_constraint_unique_user_username PASSED [  6%]
tests/test_constraints.py::test_db_constraint_unique_project_slug PASSED [ 10%]
tests/test_constraints.py::test_db_constraint_foreign_key_task_project PASSED [ 13%]
tests/test_constraints.py::test_db_constraint_foreign_key_notification_recipient PASSED [ 16%]
tests/test_constraints.py::test_cascade_delete_task_removes_dependent_records PASSED [ 20%]
tests/test_task_assignment.py::test_assign_task_success_all_5_records_created PASSED [ 40%]
tests/test_task_assignment.py::test_reassign_task_tracks_previous_assignee PASSED [ 43%]
tests/test_task_assignment.py::test_assign_task_without_status_change_omits_status_history PASSED [ 46%]
tests/test_task_assignment.py::test_assign_task_missing_task_returns_404 PASSED [ 50%]
tests/test_task_assignment.py::test_assign_task_missing_assignee_returns_404 PASSED [ 53%]
tests/test_task_assignment.py::test_assign_task_missing_assigned_by_returns_404 PASSED [ 56%]
tests/test_task_assignment.py::test_assign_task_atomic_rollback_guarantee_on_failure[1] PASSED [ 60%]
tests/test_task_assignment.py::test_assign_task_atomic_rollback_guarantee_on_failure[2] PASSED [ 63%]
tests/test_task_assignment.py::test_assign_task_atomic_rollback_guarantee_on_failure[3] PASSED [ 66%]
tests/test_task_assignment.py::test_assign_task_atomic_rollback_guarantee_on_failure[4] PASSED [ 70%]
tests/test_task_assignment.py::test_assign_task_atomic_rollback_guarantee_on_failure[5] PASSED [ 73%]
tests/test_task_assignment.py::test_get_task_history_activity_and_notifications_endpoints PASSED [ 76%]
======================== 30 passed in 5.72s ========================
```

---

## What We Learned

1. **Transaction Boundaries Belong in the Service Layer**:
   - Repositories should execute SQL statements or stage changes, but the business transaction boundary must be governed by the domain service (`TaskService.assign_task`).
   - If repositories commit early (`db.commit()`), an error in step 4 or 5 creates unrevertable orphan records in steps 1, 2, and 3.
2. **Transactional Outbox / In-DB Notifications Guarantee Consistency**:
   - Writing the notification directly to the database in the same transaction as the assignment guarantees that a notification is never sent for an assignment that rolled back.
3. **Database Constraints as Last Line of Defense**:
   - API-level uniqueness checks (`get_by_email`, `get_by_slug`) suffer from race conditions under concurrent requests. Database constraints (`UNIQUE`, `NOT NULL`, `FOREIGN KEY`) guarantee consistency at the engine level.
4. **Audit Immutability**:
   - Keeping history in append-only tables (`task_assignment_history`, `task_status_history`) ensures complete traceability for compliance and debugging.

---

## Open Questions

1. **Async Notification Worker Pattern**:
   - When external notifications (e.g. Email, Slack, Push) are required, should we use a background polling worker consuming `notification` table rows (Transactional Outbox Pattern) rather than firing third-party HTTP calls directly inside the DB transaction?
2. **Soft Deletion vs Cascading Foreign Keys**:
   - If tasks are soft-deleted (`is_deleted=True`), does cascade deletion behavior need to be replaced with soft-delete propagation?
