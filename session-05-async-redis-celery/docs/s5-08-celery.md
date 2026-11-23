# S5-08: Celery app and worker service

## What this task provides

Celery runs work outside the HTTP request. The API puts a message on a queue (the
**broker**), a separate **worker** process picks it up and runs it, and the return
value is stored in a **result backend**. TaskFlow uses the Redis service from S5-01
for both. Later tasks build on this one: S5-09 moves the assignment notification into
a retrying job, S5-10 adds Beat, and S5-11 adds Flower.

Files:

| File | Purpose |
|---|---|
| `app/worker/celery_app.py` | The `celery_app` instance and its configuration |
| `app/worker/db.py` | Worker-owned engine, `WorkerSessionLocal`, and `run_async` |
| `app/worker/tasks.py` | `taskflow.ping` and `taskflow.db_ping` |
| `compose.yaml` | `celery-worker` service |
| `tests/unit/test_celery_app.py` | Configuration and isolation tests (no broker needed) |

## 1. One Redis server, three logical databases

| URL | Used for |
|---|---|
| `redis://…:6379/0` | App cache and data structures (`REDIS_URL`, S5-01) |
| `redis://…:6379/1` | Celery broker: queued messages (`CELERY_BROKER_URL`) |
| `redis://…:6379/2` | Celery results: `celery-task-meta-<id>` keys (`CELERY_RESULT_BACKEND`) |

Separate databases keep the key spaces apart. `FLUSHDB` on the cache database does
not delete queued jobs, and `redis-cli -n 2 KEYS 'celery-task-meta-*'` shows only
results. They still share one server's memory and availability.

As with `REDIS_URL`, the defaults use `localhost` for running on your laptop.
Compose overrides them with the `redis` service hostname.

## 2. Configuration choices

**JSON only.** `task_serializer`, `result_serializer`, `accept_content` and
`result_accept_content` are all JSON. The worker refuses pickle messages, because
unpickling data from the broker can execute arbitrary code. Task arguments must
therefore be JSON-compatible: pass IDs and strings, not ORM objects or `datetime`s.

**`task_acks_late=True`.** Celery normally acknowledges a message as soon as a worker
receives it. With late acks, the worker acknowledges only after the task returns. If the
worker crashes mid-task, the message stays unacknowledged and is delivered again.
A task can therefore run more than once, so **tasks must be idempotent**. S5-09
enforces that with one notification per assignment-history ID.

**`task_reject_on_worker_lost=True`.** This complements late acks. If the pool process
is killed (OOM, `SIGKILL`), the message is requeued instead of being recorded as failed.

**`worker_prefetch_multiplier=1`.** Each pool process reserves only one extra message
at a time. A worker running a long task does not hold a batch of queued work
that idle workers could have taken.

**Time limits.** `task_soft_time_limit` (default 50s) raises `SoftTimeLimitExceeded`
inside the task so it can clean up. `task_time_limit` (default 60s) then kills
the pool process. Both are configurable through settings. Compose sets
`stop_grace_period: 60s` so a warm shutdown can finish in-flight tasks.

`result_expires=3600` removes stored results after an hour.
`broker_connection_retry_on_startup=True` keeps the worker retrying if Redis is not
ready yet.

## 3. Why the worker has its own DB session factory

The API uses `app.db.database.AsyncSessionLocal`: a pooled async engine, with one session
per HTTP request inside Uvicorn's single long-lived event loop.

Celery tasks are plain synchronous functions. To call the existing async
repositories, a task runs its coroutine with `run_async(...)` (`asyncio.run`), which
creates a **new event loop for each call**. asyncpg connections belong to the loop that
opened them. If a pooled connection from an earlier task were handed to a later
task's loop, it would fail with errors such as "attached to a different loop".

`app/worker/db.py` therefore creates `worker_engine` with `NullPool`. Each session
opens a fresh connection and closes it when the session ends, so no connection
outlives its loop. Worker code must use `WorkerSessionLocal`, never
`AsyncSessionLocal` or `get_async_session`.

```python
from app.worker.db import WorkerSessionLocal, run_async


async def _work(task_id: int) -> None:
    async with WorkerSessionLocal() as session:
        ...  # use existing repositories
        await session.commit()


@celery_app.task(name="taskflow.example")
def example(task_id: int) -> None:
    run_async(_work(task_id))
```

The trade-off is one connection setup per task. That is acceptable at this scale.
Later on, high-throughput workers could use a per-process event loop with a pool.

## 4. Run it

In Compose:

```bash
make docker-up                        # includes celery-worker
docker compose logs -f celery-worker  # look for "celery@<host> ready." and [tasks]
make celery-ping                      # prints: pong
```

Locally, with Redis and Postgres reachable on `localhost`:

```bash
make celery-worker
```

### Host port clashes

Other software often already owns the default host ports: a Homebrew Postgres on
5432, or another project's Redis on 6379. Compose publishes on
`POSTGRES_HOST_PORT` / `REDIS_HOST_PORT` (default 5432 / 6379). Set them in `.env`
and point the laptop-side URLs at the same ports:

```dotenv
POSTGRES_PORT=15432
POSTGRES_HOST_PORT=15432
TEST_DATABASE_URL=postgresql+asyncpg://<user>:<password>@localhost:15432/taskflow_test
REDIS_HOST_PORT=16379
REDIS_URL=redis://localhost:16379/0
CELERY_BROKER_URL=redis://localhost:16379/1
CELERY_RESULT_BACKEND=redis://localhost:16379/2
```

Containers are unaffected: Compose pins `POSTGRES_PORT=5432` and the Redis URLs to
the service names. The `test` service builds `TEST_DATABASE_URL` against
`postgres:5432`, so `make docker-test` does not depend on the host port.
Watch out for a native Postgres on 5432: `localhost:5432` silently reaches it
instead of the container, so the API and tests end up using different databases.

## 5. Verify

```bash
uv lock --check
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest tests/unit/test_celery_app.py

make celery-ping
docker compose exec celery-worker uv run celery -A app.worker.celery_app inspect ping
docker compose exec celery-worker uv run python -c \
  "from app.worker.tasks import db_ping; print(db_ping.delay().get(timeout=10))"
docker compose exec redis redis-cli -n 2 KEYS 'celery-task-meta-*'
```

## Verified result

- Ruff, ruff format, mypy, `uv lock --check`, and `docker compose config`: passed.
- `tests/unit/test_celery_app.py`: 7 passed. Full suite: **250 passed** both from the
  host (`uv run pytest`) and in Compose (`make docker-test`).
- Real worker (Celery 5.7.0, concurrency 2) connected to `redis://redis:6379/1`,
  registered `taskflow.ping` and `taskflow.db_ping`, and reported ready.
- `make celery-ping` printed `pong`. `inspect ping` reported 1 node online.
- `db_ping` returned `1`. Six consecutive calls in the same worker, each with a new
  event loop, all returned `1` with no loop errors.
- Result keys appeared in Redis DB 2.

The worker currently runs as root inside the container, as the API does. Celery
logs a `SecurityWarning` about this. Running both as a non-root user is a
Dockerfile change left for a follow-up.

## References

- [Celery: Using Redis](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html)
- [Celery configuration reference](https://docs.celeryq.dev/en/stable/userguide/configuration.html)
- [Celery FAQ: acks_late](https://docs.celeryq.dev/en/stable/faq.html#faq-acks-late-vs-retry)
- [SQLAlchemy: Using asyncio with multiple event loops](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-multiple-asyncio-event-loops)
