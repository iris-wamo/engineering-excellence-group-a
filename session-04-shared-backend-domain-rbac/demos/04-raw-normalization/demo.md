# Raw Import Normalization Demo

## Objective
Prove that raw third-party task payloads are stored before processing, then
validated, transformed, and normalized into PostgreSQL task records when valid.
Failed imports must remain traceable with an import ID, trace ID, processing
status, and failure reason.

## Scenario
An external integration sends task data to `POST /imports/tasks/raw`. TaskFlow
must keep the original raw payload in MongoDB even when validation or reference
lookups fail. Valid payloads should create relational `task` records linked back
to the MongoDB audit document.

## Commands / Steps Used
Run the focused raw import tests:

```bash
uv run pytest tests/test_raw_import_normalization.py
```

Run the route-level import tests:

```bash
uv run pytest tests/test_mongo_import.py
```

Example successful request:

```bash
curl -X POST http://localhost:8000/imports/tasks/raw \
  -H "Content-Type: application/json" \
  -d '{
    "source": "vendor_csv",
    "payload": {
      "title": "Follow up with customer",
      "project_title": "Customer Portal",
      "assignee_email": "owner@example.com",
      "priority": "high",
      "description": "Imported from partner CSV"
    }
  }'
```

Example failed request:

```bash
curl -X POST http://localhost:8000/imports/tasks/raw \
  -H "Content-Type: application/json" \
  -d '{
    "source": "vendor_csv",
    "payload": {
      "title": "Cannot normalize yet",
      "project_title": "Unknown Project",
      "assignee_email": "owner@example.com",
      "priority": "medium"
    }
  }'
```

## Expected Behavior
Successful imports are marked `completed`, include `postgres_task_id`, and return
a normalized task record. Failed imports are marked `failed`, keep the raw
payload, and include `error_message` / `failure_reason`.

All imports start as `pending` in MongoDB before validation starts.

## Actual Findings
The implementation stores each raw payload first in `raw_task_imports`, assigns
`import_id` and `trace_id`, validates the payload, resolves the PostgreSQL
project and assignee, and creates one normalized task record for valid imports.
Invalid payloads and failed lookups update the original MongoDB document to
`failed` without creating normalized records.

## Evidence
Successful response shape:

```json
{
  "processed_status": "completed",
  "postgres_task_id": "created-task-uuid",
  "normalized_records": [
    {
      "task_id": "created-task-uuid",
      "title": "Follow up with customer",
      "project_id": "resolved-project-uuid",
      "assignee_id": "resolved-user-uuid",
      "priority": "high",
      "status": "TODO"
    }
  ],
  "error_message": null
}
```

Failed response shape:

```json
{
  "processed_status": "failed",
  "postgres_task_id": null,
  "normalized_records": [],
  "error_message": "Project 'Unknown Project' was not found"
}
```

## What We Learned
Raw import processing should be audit-first. Storing the raw document before
validation prevents data loss, makes failed integrations debuggable, and keeps
the normalized PostgreSQL model clean.

## Open Questions
Batch import support could reuse the `normalized_records` list shape, but this
PR keeps the scope to one raw task payload per request.
