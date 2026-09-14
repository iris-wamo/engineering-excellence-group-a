# Issue #11 — Transaction-Safe Assignment Schema Design

## Objective

Define the supporting database schema required for the transaction-safe task assignment flow described in Session 3.

The schema is intended to support a single transaction boundary covering the task assignment and its related history, activity, and notification records.

> This document contains the schema design for Part A. The tables and transaction-safe assignment flow are not implemented at this stage.

## Proposed Schema

### `task_assignment_history`

Stores the history of task assignment changes.

- `id` — UUID, Primary Key
- `task_id` — UUID, Foreign Key → `task.id`, NOT NULL
- `previous_assignee_id` — UUID, Foreign Key → `user.id`, nullable
- `new_assignee_id` — UUID, Foreign Key → `user.id`, NOT NULL
- `assigned_by_id` — UUID, Foreign Key → `user.id`, NOT NULL
- `created_at` — timestamp, NOT NULL

### `task_status_history`

Stores task status changes associated with task activity.

- `id` — UUID, Primary Key
- `task_id` — UUID, Foreign Key → `task.id`, NOT NULL
- `previous_status` — `taskstatus`, nullable
- `new_status` — `taskstatus`, NOT NULL
- `changed_by_id` — UUID, Foreign Key → `user.id`, NOT NULL
- `created_at` — timestamp, NOT NULL

### `activity_log`

Stores task-related actions for activity and audit tracking.

- `id` — UUID, Primary Key
- `task_id` — UUID, Foreign Key → `task.id`, NOT NULL
- `actor_id` — UUID, Foreign Key → `user.id`, NOT NULL
- `action` — VARCHAR, NOT NULL
- `details` — JSONB, nullable
- `created_at` — timestamp, NOT NULL

### `notification`

Stores notifications generated as part of task activity.

- `id` — UUID, Primary Key
- `recipient_id` — UUID, Foreign Key → `user.id`, NOT NULL
- `task_id` — UUID, Foreign Key → `task.id`, NOT NULL
- `type` — VARCHAR, NOT NULL
- `message` — VARCHAR, NOT NULL
- `is_read` — BOOLEAN, NOT NULL, default `false`
- `created_at` — timestamp, NOT NULL

## Relationships

The proposed foreign-key relationships are:

- `task_assignment_history.task_id` → `task.id`
- `task_assignment_history.previous_assignee_id` → `user.id`
- `task_assignment_history.new_assignee_id` → `user.id`
- `task_assignment_history.assigned_by_id` → `user.id`
- `task_status_history.task_id` → `task.id`
- `task_status_history.changed_by_id` → `user.id`
- `activity_log.task_id` → `task.id`
- `activity_log.actor_id` → `user.id`
- `notification.recipient_id` → `user.id`
- `notification.task_id` → `task.id`

## Transaction Boundary

The intended task-assignment transaction will cover:

1. Updating the task assignee.
2. Creating the assignment history record.
3. Recording the relevant status change.
4. Creating the activity log entry.
5. Creating the notification.

If any part of the operation fails, the transaction should roll back so that partial changes are not persisted.

The transaction implementation and rollback tests will be added after the supporting database tables are available.

## Constraints

The proposed schema uses database-level constraints for required fields and relationships, including:

- Primary keys on all supporting tables.
- Foreign keys to the existing `task` and `user` tables.
- `NOT NULL` constraints for required fields.
- `previous_assignee_id` and `previous_status` remain nullable because a task may previously have had no assignee or no previous status.

The existing `user.email` and `user.username` uniqueness constraints are already present in the baseline migration, so they do not need to be duplicated.

Additional indexes or constraints can be finalized during the migration implementation and review.

## Design Decisions

### Assignment History

A separate history table preserves the previous and new assignee for each assignment instead of keeping only the current assignee on the task.

### Status History

A separate status history table preserves changes to task status over time.

### Activity Log

The activity log provides a general record of actions performed on a task. The `JSONB` `details` field allows additional action-specific information to be stored without requiring a new column for every activity type.

### Notification

Notifications are represented as database records so notification creation can participate in the same transaction as the assignment operation.

## Implementation Dependency

This schema is the design input for the migration work under Issue #12.

Once the supporting tables have been created through the migrations, the transaction-safe assignment flow and rollback tests can be implemented against the actual database schema.

## Current Status

- **Part A — Schema Design**: Complete (Schema, constraints, and relationships mapped).
- **Part B — Transaction-Safe Assignment Flow**: Complete (`/tasks/{task_id}/assign` 5-step atomic flow, rollback guarantee tests across all 5 failure stages, database constraint tests, standalone demo script, and documentation in `demos/01-transaction-safe-assignment/demo.md`).