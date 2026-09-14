# Session 3 — DB Transactions & Migrations

## Correctness SLO

Task assignment should not create partial writes. If assignment fails, task assignment, assignment history, status history, activity log, and notification record should roll back together.

### Scope & Execution Plan

- **Part A (Schema & Models)**: Define supporting SQLAlchemy models (`TaskAssignmentHistory`, `TaskStatusHistory`, `ActivityLog`, `Notification`), `Project.slug` unique constraint, and relationship mappings. *(Status: Completed)*
- **Part B (Transaction Service & Rollback)**: Implement 5-step atomic task assignment service (`/tasks/{id}/assign`), partial failure rollback handling, unit/integration tests, standalone demo script, and demo documentation. *(Status: Completed)*

### Correctness Verification Targets

- **100% Atomic Commits**: 5-step transaction (task assignee update, assignment history, status history, activity log, and notification) commits atomically on success.
- **Zero Partial Writes Guarantee**: If an exception occurs at any of steps 1 through 5, all staged records are rolled back. 0 orphan records are left in the database.
- **Audit Immutability**: All assignment transitions preserve full lineage (`previous_assignee_id` -> `new_assignee_id`).
- **Database Constraint Defense**: Storage-level uniqueness on `user.email`, `user.username`, and `project.slug`, and foreign key enforcement on all relationships.


## Migration Safety SLO

Database migrations must be safely upgradeable, tested against existing data when applicable, and reversible where rollback is supported.

### Safety Targets

- 100% of migrations must successfully upgrade from their previous revision.
- Migrations modifying existing tables must be tested against existing data.
- `NOT NULL` additions must have an explicit default or backfill strategy.
- Supported downgrade paths must be tested.
- No migration should unintentionally cause data loss.

