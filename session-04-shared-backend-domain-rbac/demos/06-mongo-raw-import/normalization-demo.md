# Normalization Demo

## Goal

Show the raw import workflow preserving every payload while converting valid
imports into normalized TaskFlow task records.

## Successful Import

Request:

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

Expected result:

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

MongoDB keeps the original payload plus `import_id`, `trace_id`, `received_at`,
and `processed_at`.

## Failed Import

Request with a missing project:

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

Expected result:

```json
{
  "processed_status": "failed",
  "postgres_task_id": null,
  "normalized_records": [],
  "error_message": "Project 'Unknown Project' was not found"
}
```

The failed import still remains in `raw_task_imports` with its original payload
and failure reason.

## Listing Imports

```bash
curl http://localhost:8000/imports/tasks/raw?status=failed
curl http://localhost:8000/imports/tasks/raw?status=completed
```

These queries read the MongoDB audit records and return the trace fields, raw
payload, processing status, normalized records, and failure details.

