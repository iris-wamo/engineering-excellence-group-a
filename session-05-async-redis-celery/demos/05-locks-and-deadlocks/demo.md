# Demo: Row Lock and Deadlock Simulation

## Loom Video
https://www.loom.com/share/85d37bb2433243a883b55cc3c14d847e

## Objective
What are we trying to prove?
- Demonstrate how concurrent database transactions updating multiple rows in inconsistent order create circular lock dependencies (Row-Level Locking).
- Observe PostgreSQL's automatic deadlock detection mechanism
- Understand how backend developers can prevent and handle deadlocks in Production

## Scenario Choice & Rationale
Which scenario type was chosen and why?
- **Selected Scenario**: *Deadlock via Reverse Update Order (Circular Wait)*.
### Production Problem Description:
I tried two concurrent API requests to perform multi-row status updates on the same two tasks (`Task A` and `Task B`) within a shared project:
- **Transaction 1 (User A)**: Updates `Task A` first, then attempts to update `Task B`.
- **Transaction 2 (User B)**: Updates `Task B` first, then attempts to update `Task A`.
Both transactions hold their initial row locks open while attempting to acquire the row lock held by the other transaction, causing a circular wait freeze.

## Commands / Steps Used
I used the script simulate_deadlock.py for this, its in script folder you can get it from there.
### Automated Python Simulation Command
```bash
uv run python scripts/simulate_deadlock.py
```

## Expected Behavior
What should happen?
- Both transactions acquire their first row lock (`RowExclusiveLock`) successfully.
- When Transaction 1 attempts to lock `Task B`, it blocks because Transaction 2 holds `Task B`.
- When Transaction 2 attempts to lock `Task A`, it blocks because Transaction 1 holds `Task A`.
- PostgreSQL's deadlock detector thread detects the circular dependency graph after `deadlock_timeout` (default 1 second), automatically cancels one of the transactions with `ERROR: deadlock detected`, and allows the remaining transaction to complete cleanly.

## Actual Findings
Everything happened as expected, check in the Loom Video

## Evidence
### Terminal Output from Live Simulation Execution:

```text
============================================================
PostgreSQL Row Lock & Deadlock Simulation
============================================================
✅ Test data seeded successfully: Task A and Task B created.

Starting Transaction 1 and Transaction 2 concurrently...

[Transaction 1] BEGIN
[Transaction 1] Locking Task A...
[Transaction 2] BEGIN
[Transaction 2] Locking Task B...
[Transaction 1] Task A locked. Sleeping 1 second...
[Transaction 2] Task B locked. Sleeping 1 second...
[Transaction 1] Attempting to lock Task B...
[Transaction 2] Attempting to lock Task A...
[Transaction 2] SUCCESS (No deadlock)

❌ [Transaction 1 Error]: DBAPIError: (sqlalchemy.dialects.postgresql.asyncpg.Error) <class 'asyncpg.exceptions.DeadlockDetectedError'>: deadlock detected
DETAIL:  Process 863 waits for ShareLock on transaction 748; blocked by process 864.
Process 864 waits for ShareLock on transaction 747; blocked by process 863.
HINT:  See server log for query details.
[SQL: UPDATE task SET status = 'DONE' WHERE id = $1]
[parameters: ('22222222-2222-2222-2222-222222222222',)]
```

## What We Learned

1. **Row Lock Lifetime**: Row locks acquired by `UPDATE`, `DELETE`, or `SELECT FOR UPDATE` are held by PostgreSQL **until the transaction commits or rolls back**. They are not released immediately after the individual SQL line finishes.
2. **Deadlock Cause**: Deadlocks do not happen because a single row is updated. They happen when multiple rows are updated in **inconsistent sequence** across concurrent open transactions.
3. **Handling Strategies**:
   - **Deterministic Lock Ordering (Primary Prevention)**: Always sort target entity IDs before executing multi-row updates in business logic (`sorted_task_ids = sorted(task_ids)`). If all requests lock `Task A` before `Task B`, circular wait is mathematically impossible.
   - **Application-Level Retry Decorator (`@retry_on_deadlock`)**: Because deadlocks are transient, wrapping service methods in a retry loop (retrying 2–3 times with exponential backoff when catching `DeadlockDetectedError`) allows the aborted transaction to succeed on retry without crashing the user's API request with HTTP 500.
   - **Fail-Fast with `NOWAIT`**: Use `SELECT ... FOR UPDATE NOWAIT` in SQLAlchemy when acquiring locks. If a row is locked, it raises an immediate error that can be handled as an HTTP `409 Conflict` instead of freezing into a deadlock.

