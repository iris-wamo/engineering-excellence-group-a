# Demo 06: MongoDB Raw Import Payload Mini Use Case

## Loom Video
https://www.loom.com/share/810139006ff14d7f859cc6b4f93da2e1

## Objective
What are we trying to prove?
- Demonstrate **Polyglot Persistence** (Document DB + Relational DB) by storing third-party raw task import payloads in MongoDB before creating normalized records in PostgreSQL.
- Prove **100% Import Traceability & Debuggability**: If an incoming payload fails PostgreSQL validation (e.g. invalid assignee email or missing project), the original raw payload is preserved in MongoDB with `processed_status: "failed"` and the exact error traceback for support debugging.
- Demonstrate linkage between MongoDB document BSON `_id` and PostgreSQL task UUID `postgres_task_id`.

## Scenario
What production-style issue are we simulating?
- External third-party integrations send raw JSON task payloads to TaskFlow API endpoint `POST /imports/tasks/raw`.
- **Scenario A (Successful Import)**: Raw payload contains valid `project_title` and `assignee_email`. Raw JSON is stored in MongoDB (`processed_status: "pending"` $\rightarrow$ `"success"`), and a clean normalized `Task` row is created in PostgreSQL.
- **Scenario B (Failed Import Debugging Use Case)**: Raw payload contains a non-existent `assignee_email` (`"nonexistent_user@example.com"`). PostgreSQL lookup fails. Raw payload is preserved in MongoDB with `processed_status: "failed"` and `error_message: "Assignee with email 'nonexistent_user@example.com' not found in PostgreSQL"`. Zero rows are inserted into PostgreSQL.

## Steps Used

### 1. Submit Successful Raw Import Payload (cURL)
```bash
curl -X POST http://localhost:8000/imports/tasks/raw \
  -H "Content-Type: application/json" \
  -d '{
    "source": "external_csv_import",
    "payload": {
      "title": "Fix login authentication bug",
      "project_title": "Import Demo Project",
      "assignee_email": "import_user@example.com",
      "priority": "high",
      "description": "Users getting HTTP 500 on login"
    }
  }'
```

### 2. Submit Failed Raw Import Payload (cURL)
```bash
curl -X POST http://localhost:8000/imports/tasks/raw \
  -H "Content-Type: application/json" \
  -d '{
    "source": "external_csv_import",
    "payload": {
      "title": "Broken task with bad email",
      "project_title": "Import Demo Project",
      "assignee_email": "nonexistent_user@example.com",
      "priority": "high"
    }
  }'
```

### 3. List Raw Import Documents from MongoDB (cURL)
```bash
# List all failed raw import payloads for debugging:
curl -X GET "http://localhost:8000/imports/tasks/raw?status=failed"
```

### 4. Run Automated Pytest Integration Suite
```bash
uv run pytest -v tests/test_mongo_import.py
```

## MongoDB Collection Design
The MongoDB collection is named **`raw_task_imports`** inside database `taskflow_imports`.

### MongoDB Document Schema:
```typescript
interface RawTaskImportDocument {
  _id: ObjectId;                
  source: string;          
  payload: {                    
    title: string;
    project_title: string;
    assignee_email: string;
    priority: string;
    description?: string;
  };
  processed_status: "pending" | "success" | "failed";
  postgres_task_id: string | null;
  error_message: string | null;   
  received_at: Date;              
  processed_at: Date | null;     
}
```

## Expected Behavior
What should happen?
- Every incoming raw import request is saved to MongoDB first before relational processing begins.
- Valid payloads create normalized PostgreSQL task records and link `postgres_task_id` in MongoDB.
- Invalid payloads fail gracefully, leaving 0 orphan records in PostgreSQL, but preserving the raw payload and exact error message in MongoDB for debugging.

## Actual Findings
What actually happened?
- Executed `POST /imports/tasks/raw` with valid payload: MongoDB record created with `processed_status: "success"` and `postgres_task_id: "c9b2e1f4-..."`. PostgreSQL task created cleanly.
- Executed `POST /imports/tasks/raw` with bad email: MongoDB record created with `processed_status: "failed"` and `error_message: "Assignee with email 'nonexistent_user@example.com' not found in PostgreSQL"`. PostgreSQL task creation rolled back.
- Executed `GET /imports/tasks/raw?status=failed`: Successfully retrieved the failed document payload from MongoDB for debugging.

## Evidence

### 1. Successful Import Document in MongoDB:
```json
{
  "_id": "65f1234567890abcdef12345",
  "source": "external_csv_import",
  "payload": {
    "title": "Fix login authentication bug",
    "project_title": "Import Demo Project",
    "assignee_email": "import_user@example.com",
    "priority": "high",
    "description": "Users getting HTTP 500 on login"
  },
  "processed_status": "success",
  "postgres_task_id": "c9b2e1f4-3a7d-4e90-8b12-9876543210fe",
  "error_message": null,
  "received_at": "2026-09-18T20:15:00.000Z",
  "processed_at": "2026-09-18T20:15:01.000Z"
}
```

### 2. Failed Import Document in MongoDB (Debugging Use Case):
```json
{
  "_id": "65f1234567890abcdef12346",
  "source": "external_csv_import",
  "payload": {
    "title": "Broken task with bad email",
    "project_title": "Import Demo Project",
    "assignee_email": "nonexistent_user@example.com",
    "priority": "high"
  },
  "processed_status": "failed",
  "postgres_task_id": null,
  "error_message": "Assignee with email 'nonexistent_user@example.com' not found in PostgreSQL",
  "received_at": "2026-09-18T20:15:05.000Z",
  "processed_at": "2026-09-18T20:15:05.100Z"
}
```

### 3. Motor Async Python Driver Usage Snippets:

#### Staging Raw Payload in MongoDB:
```python
mongo_doc = {
    "source": request.source,
    "payload": request.payload.model_dump(),
    "processed_status": "pending",
    "postgres_task_id": None,
    "error_message": None,
    "received_at": datetime.now(timezone.utc).replace(tzinfo=None),
}
insert_result = await db_mongo["raw_task_imports"].insert_one(mongo_doc)
```

#### Updating MongoDB Document on Failure:
```python
await db_mongo["raw_task_imports"].update_one(
    {"_id": insert_result.inserted_id},
    {
        "$set": {
            "processed_status": "failed",
            "postgres_task_id": None,
            "error_message": str(e),
            "processed_at": datetime.now(timezone.utc).replace(tzinfo=None),
        }
    },
)
```

## What We Learned

1. **Polyglot Persistence Pattern**: Combining a schema-less Document DB (MongoDB) for raw payload audit stores with a relational DB (PostgreSQL) for normalized core application data delivers both **high ingestion reliability** and **strict data integrity**.
2. **Debugging Third-Party Integrations**: Storing raw payloads in MongoDB ensures zero data loss when external webhooks send invalid payloads. Support engineers can inspect MongoDB, correct the data, and re-process failed imports without requesting external re-transmission.
3. **Async Driver Efficiency**: Using Motor (`AsyncIOMotorClient`) inside FastAPI route handlers ensures non-blocking I/O during MongoDB writes, preserving high API concurrency.

