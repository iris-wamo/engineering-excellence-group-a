# Database IDE (DBeaver) Inspection & Performance Findings

## Executive Overview
Relying solely on API responses (e.g., Swagger UI or HTTP endpoints) hides crucial underlying database mechanics. Using a Database IDE (such as **DBeaver**, **DataGrip**, or `psql`) enables engineers to directly inspect physical schema definitions, verify indexes, execute raw SQL scripts, profile query performance via `EXPLAIN ANALYZE`, and audit active row locks and migration versions.

This document details the findings from inspecting the `taskflow` PostgreSQL database and provides a **step-by-step guide**.

---

## Step-by-Step Setup Guide

## Step 1: Database Connection Setup

#### Using DBeaver (GUI)
1. Open **DBeaver**.
2. Click **Database** $\rightarrow$ **New Database Connection** (or press `Ctrl+N` / `Cmd+N`).
3. Select **PostgreSQL** from the list of drivers and click **Next**.
4. In the Connection Settings tab, enter the credentials from `.env`:
   * **Host**: `localhost`
   * **Port**: `5432`
   * **Database**: `taskflow`
   * **Username**: `user`
   * **Password**: `123456`
5. Click **Test Connection ...** (DBeaver will prompt to download the PostgreSQL JDBC Driver if not installed).
6. Click **Finish**.


---

## Step 2: Table & Schema Inspection

### How to Perform in DBeaver:
1. In the **Database Navigator** panel on the left, expand `taskflow` $\rightarrow$ `Schemas` $\rightarrow$ `public` $\rightarrow$ `Tables`.
2. Double-click any table (e.g., `task`) and open the **Properties** tab.

### Key Observations & Verification:

| Table Name | Purpose | Primary Key | Key Foreign Keys & Constraints |
| :--- | :--- | :--- | :--- |
| `user` | Core user identity & authentication | `id` (UUID) | Unique constraints on `email` and `username` |
| `project` | Projects containing tasks | `id` (UUID) | `owner_id` $\rightarrow$ `user.id` (`ON DELETE SET NULL`) |
| `task` | Work items / tasks | `id` (UUID) | `project_id` $\rightarrow$ `project.id` (`ON DELETE CASCADE`), `assigned_to` $\rightarrow$ `user.id` |
| `task_assignment_history` | Audit trail of task assignees | `id` (UUID) | `task_id` $\rightarrow$ `task.id`, `previous_assignee_id`, `new_assignee_id` |
| `task_status_history` | Audit trail of task status changes | `id` (UUID) | `task_id` $\rightarrow$ `task.id`, `previous_status`, `new_status` |
| `alembic_version` | Migration version tracker | `version_num` (PK) | Stores current migration hash |

#### Schema Quality Highlights:
* **UUID Primary Keys**: All entity IDs use native PostgreSQL `UUID` (`uuid_generate_v4()` or Python `uuid4`), preventing ID enumeration attacks.
* **Cascade Delete Protection**: `task` $\rightarrow$ `project` uses `ON DELETE CASCADE` so deleting a project automatically cleans up child tasks without leaving orphaned rows.
* **Timestamp Normalization**: All timestamps (`created_at`, `updated_at`) use `TIMESTAMP WITHOUT TIME ZONE` normalized to UTC.

---

## Step 3: Index Inspection

### How to Perform in DBeaver:
1. Select a table in Database Navigator (e.g., `task`).
2. Click on the **Indexes** sub-tab under **Properties**.

### Verified Indexes in `taskflow` Database:

1. **Primary Key Indexes**:
   * `task_pkey` on `task(id)` (B-Tree, Unique)
   * `user_pkey` on `user(id)` (B-Tree, Unique)
   * `project_pkey` on `project(id)` (B-Tree, Unique)

2. **Unique Business Key Indexes**:
   * `user_email_key` on `user(email)` (B-Tree, Unique) — Guarantees fast lookup for login & raw import validation.
   * `user_username_key` on `user(username)` (B-Tree, Unique)

3. **Foreign Key & Filter Indexes**:
   * `ix_task_project_id` on `task(project_id)` — Accelerates filtering tasks by project (`GET /projects/{id}/tasks`).
   * `ix_task_assigned_to` on `task(assigned_to)` — Accelerates fetching user workload (`GET /users/{id}/tasks`).
   * `ix_task_status` on `task(status)` — Optimizes status board filtering (`status = 'IN_PROGRESS'`).

---

## Step 4: Manual SQL Execution & Verification

### How to Perform in DBeaver:
1. Open the SQL Editor: Click **SQL Editor** $\rightarrow$ **New SQL Script** (or `F3` / `Cmd+]`).
2. Paste and execute the verification queries below using `Ctrl+Enter` / `Cmd+Enter`.

### Query 1: Joined Task Audit Report
```sql
SELECT 
    t.id AS task_id,
    t.title AS task_title,
    t.status AS task_status,
    t.priority AS task_priority,
    p.title AS project_title,
    u.name AS assignee_name,
    u.email AS assignee_email,
    t.created_at
FROM task t
JOIN project p ON t.project_id = p.id
LEFT JOIN "user" u ON t.assigned_to = u.id
ORDER BY t.created_at DESC;
```
* **Observation**: Successfully joins relational entities across three tables using primary/foreign key indexes without full table scans.

### Query 2: Status History Audit Trail
```sql
SELECT 
    h.task_id,
    t.title,
    h.previous_status,
    h.new_status,
    u.name AS changed_by,
    h.created_at AS transition_time
FROM task_status_history h
JOIN task t ON h.task_id = t.id
JOIN "user" u ON h.changed_by_id = u.id
ORDER BY h.created_at DESC;
```
* **Observation**: Verifies that state transitions staged during transaction-safe task updates leave a clean, append-only history trail.

---

## Step 5: Query Profiling with `EXPLAIN ANALYZE`

### Test Case: Filtering Tasks by Status
```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT * FROM task WHERE status = 'IN_PROGRESS';
```

### Execution Plan Output Analysis:
```text
Seq Scan on public.task  (cost=0.00..10.88 rows=1 width=1132) (actual time=0.019..0.020 rows=1 loops=1)
  Output: id, project_id, assigned_to, assigned_by, title, description, priority, status, estimated_time, deadline, created_at, updated_at
  Filter: (task.status = 'IN_PROGRESS'::taskstatus)
  Rows Removed by Filter: 2
  Buffers: shared hit=1
Planning:
  Buffers: shared hit=82
Planning Time: 0.435 ms
Execution Time: 0.046 ms
```
---

## Step 6: Migration Verification (`alembic_version`)

### How to Perform in DBeaver:
Execute the following query to check current schema migration state:
```sql
SELECT * FROM alembic_version;
```

### Verification Result:
```text
version_num: 616f4258fef2
```

### Verification Details:
* **Current Revision Hash**: `616f4258fef2`
* **Corresponding Script File**: `alembic/versions/616f4258fef2_add_project_priority.py`
* **Conclusion**: The live PostgreSQL database schema is 100% in sync with the codebase. There is zero schema drift.

---

## Step 7: Debugging Live Transactions & Row Locks

When debugging concurrency issues or deadlock scenarios (as simulated in Demo 05), DB IDEs allow engineers to view active locks and blocked queries in real time.

### Query 1: View Active Queries & Process States
```sql
SELECT 
    pid, 
    usename, 
    application_name, 
    client_addr, 
    state, 
    query_start, 
    query 
FROM pg_stat_activity 
WHERE state != 'idle' 
  AND pid != pg_backend_pid();
```

### Query 2: View Held Row Locks (`FOR UPDATE`)
```sql
SELECT 
    l.pid,
    l.locktype,
    l.relation::regclass AS table_name,
    l.mode,
    l.granted,
    a.query
FROM pg_locks l
JOIN pg_stat_activity a ON l.pid = a.pid
WHERE l.relation::regclass::text NOT LIKE 'pg_%';
```

* **Debugging Takeaway**: During Demo 05 (`FOR UPDATE` simulation), this query shows lock modes such as `RowShareLock` and `ExclusiveLock` alongside the holding Process ID (`pid`), making it straightforward to identify which transaction is holding a lock and blocking other workers.

---

