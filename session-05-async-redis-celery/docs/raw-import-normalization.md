# Raw Import Normalization Design

## Scope

Task 2 owns the import workflow that moves an external raw task payload into the
TaskFlow domain model:

```text
Raw Payload -> Store Raw -> Validate -> Transform -> Normalize -> Task Record
```

The design deliberately stores the raw document before any validation work starts.
That means every import attempt is traceable, including malformed payloads and
payloads that reference missing PostgreSQL records.

## Data Flow

1. `POST /imports/tasks/raw` receives a source name and raw JSON payload.
2. `ImportService` writes the raw payload to MongoDB collection
   `raw_task_imports` with:
   - `processed_status = "pending"`
   - `import_id`
   - `trace_id`
   - original `payload`
   - `received_at`
3. The stored payload is validated with `RawTaskPayload`.
4. PostgreSQL references are resolved:
   - project by `project_title`
   - assignee by `assignee_email`
5. The payload is transformed into a normalized `Task` row:
   - priority maps to `TaskPriority`
   - status starts as `TaskStatus.TODO`
   - project and assignee become UUID foreign keys
6. The MongoDB audit document is updated:
   - `completed` with `postgres_task_id` and `normalized_records`
   - `failed` with `failure_reason` and `error_message`

## Traceability Fields

`import_id` is the stable import identifier exposed to callers and stored in the
Mongo audit document. It mirrors the Mongo document ID for easy lookup.

`trace_id` is a separate correlation ID for logs or distributed tracing. It is
created before validation and follows both successful and failed imports.

`processed_status` uses the explicit state set required by the specification:
`pending`, `completed`, and `failed`.

## Failure Behavior

Failures never delete the raw document. Validation errors, missing projects,
missing assignees, and PostgreSQL write failures all update the same Mongo record
to `failed`.

The service also rolls back the PostgreSQL session on failure. If validation fails
before any PostgreSQL write, the rollback is still harmless and keeps the failure
path consistent.

## Normalized Record Shape

The response and audit document include `normalized_records` for completed imports.
For the current single-task import flow, the list contains one record:

```json
{
  "task_id": "uuid",
  "title": "Imported task",
  "project_id": "uuid",
  "assignee_id": "uuid",
  "priority": "high",
  "status": "TODO"
}
```

Keeping this as a list leaves room for batch imports without changing the audit
contract.

## Tests

`tests/test_raw_import_normalization.py` covers the core contract without requiring
a live MongoDB server:

- raw payload is stored as `pending` before normalization
- valid payload creates a completed import and normalized task record
- invalid payload remains stored with a failure reason
- listing imports can filter by `pending`, `completed`, or `failed`

