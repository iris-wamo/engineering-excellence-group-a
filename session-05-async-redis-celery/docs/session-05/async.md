# S5-03: Task summary, blocking vs async

Issue: [#39](https://github.com/iris-wamo/engineering-excellence-group-a/issues/39)

## The endpoint

`GET /tasks/summary?mode=async|blocking` (default `async`). Requires a bearer token.

```json
{
  "mode": "async",
  "by_status": {"todo": 3, "in_progress": 1, "in_review": 0, "done": 2, "cancelled": 0},
  "total": 6,
  "overdue": 1,
  "assigned_to_me": 2,
  "external": {"status": "ok", "elapsed_ms": 301.2, "data": {"service": "reporting", "healthy": true}, "detail": null},
  "elapsed_ms": 305.7
}
```

- **Scope (RBAC):** admins count every task; managers and members count only
  tasks in projects they belong to. `assigned_to_me` is always the caller's own tasks.
- **Overdue:** `due_date < now()` and status is not `done` / `cancelled`.
- **External call:** a fake reporting service. It is always wrapped in
  `asyncio.wait_for`. On timeout the counts still come back with
  `"external": {"status": "timeout"}`; a simulated failure gives `"error"`.
  The endpoint never hangs.

### Reproducing timeout / failure

| How | Setting |
| --- | --- |
| Per request | `?external_delay=5` (seconds), `?external_fail=true` |
| Env (`.env`) | `SUMMARY_EXTERNAL_DELAY_SECONDS` (0.3), `SUMMARY_EXTERNAL_TIMEOUT_SECONDS` (1.0), `SUMMARY_EXTERNAL_FAIL` (false) |

Any delay above the timeout gives `"timeout"`.

## The two modes

| | `async` | `blocking` |
| --- | --- | --- |
| 3 count queries | at the same time, `asyncio.gather`, one session each | one after another |
| External call | `await asyncio.sleep(delay)` | `time.sleep(delay)` inside `async def` |
| Event loop during the call | free, serves other requests | frozen, nothing else on this worker runs |

Why one session per query in async mode: a single `AsyncSession` cannot run
two statements at once, so `asyncio.gather` on one session would fail.

## Timing results

`make demo-async` fires N concurrent requests per mode against one uvicorn
worker (local Postgres, seeded with `make seed-rbac`, logged in as `admin`).
External delay 0.3 s, timeout 1 s.

| N | async wall | blocking wall | async avg latency | blocking avg latency |
| --- | --- | --- | --- | --- |
| 10 | 0.6 s | 3.2 s | 0.52 s | 1.86 s |
| 20 | 0.6 s | 6.4 s | 0.51 s | 3.52 s |
| 50 | 0.8 s | 15.7 s | 0.67 s | 8.25 s |

Timeout run (`make demo-async N=20 DELAY=2`, timeout 1 s): all 20 requests
returned `external.status = "timeout"` with the counts filled in.
Async wall time was 1.3 s; blocking was 20.5 s.

What the numbers show:

- **Async stays flat.** The waits overlap, so 50 requests take about as long
  as one.
- **Blocking grows linearly** (about N x 0.3 s). Each `time.sleep` holds the
  only event loop, so requests queue behind each other. The slowest request
  waits for everyone ahead of it.
- **`wait_for` cannot save blocking code.** It can only cancel at an `await`.
  A `time.sleep` (or sync `requests.get`) never yields, so the timeout cannot
  fire while it runs. The blocking variant only stays bounded because the
  "client" has its own timeout, like `requests.get(url, timeout=1)`. Even then
  each request still freezes the loop for up to the full timeout.

## Where async helps

- Work that **waits**: network calls, DB queries, other services. While one
  request waits, the loop serves others.
- **Independent** pieces of work in one request: `gather` turns
  `a + b + c + external` into roughly `max(a, b, c, external)`.
- Putting a **hard upper bound** on slow dependencies with `wait_for`, and
  returning partial data instead of failing.

## Where async does not help (or hurts)

- **CPU-bound work** (hashing, big JSON, number crunching). It never yields,
  so it blocks the loop just like `time.sleep`. Use a thread/process pool or a
  Celery worker.
- **Blocking libraries** inside `async def` (`requests`, `time.sleep`, sync
  DB drivers). Use the async version (`httpx.AsyncClient`, `asyncpg`), or move
  the call off the loop with `asyncio.to_thread`, or make the route a plain
  `def` so FastAPI runs it in its threadpool.
- **Tiny, fast queries.** Our three counts take a few ms each. Running them
  together saves little; the real win here is overlapping the external call.
- **Connection pools.** Fan-out multiplies connections per request. We hit this
  in the demo: each request held its auth session's connection while waiting
  for three more, and 20 concurrent requests exhausted the pool
  (5 + 10 overflow) and hung until the 30 s pool timeout. The fix: the route
  closes the request session (`await db.close()`) before fanning out. Rule of
  thumb: concurrent queries per request x concurrent requests must fit the pool.

## How to run

```bash
make migrate && make seed-rbac
make run                         # terminal 1
make demo-async                  # terminal 2 (N=20)
make demo-async N=50 DELAY=2     # timeout path

uv run pytest tests/integration/test_task_summary.py tests/auth/test_task_summary_rbac.py
```

## Tests

- `tests/integration/test_task_summary.py` (no DB, repositories faked):
  response shape in both modes, default mode / bad mode, RBAC scoping for
  admin / manager / member, 401 without a token, timeout path in both modes
  (from query param and from settings), failure path, `wait_for` cancelling
  the async call, and an event-loop check: 5 concurrent async summaries
  overlap, 5 blocking ones queue and starve a background ticker task.
- `tests/auth/test_task_summary_rbac.py` (real test DB): manager, member,
  outsider and admin get correctly scoped counts; overdue skips a cancelled
  task that is past its due date.
