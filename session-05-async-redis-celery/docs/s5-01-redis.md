# S5-01: Redis stack and shared async client

## What this task provides

Redis is a separate server that stores keys and values and offers data structures
such as counters and streams. TaskFlow will use it in later tasks for caching and
messaging. PostgreSQL remains the source of truth for business records.

The Python `redis` package (redis-py) is the client library. `redis.asyncio` is its
async API; installing a separate `aioredis` package is unnecessary.

## 1. Compose starts the server

`compose.yaml` adds `redis:7-alpine`. The image tag selects Redis 7 on Alpine.
`redis_data:/data` mounts a named Docker volume. Redis runs with append-only
persistence enabled, so writes can survive container replacement. This does not
make the development service a production high-availability system.

The host port is bound to `127.0.0.1:6379` for local development. Containers can
reach Redis on the Compose network using its service name, `redis`.

The healthcheck runs `redis-cli ping`. A running container may still be starting
its server; `condition: service_healthy` makes API and test startup wait until
Redis answers. This startup check does not monitor application dependencies on
every HTTP request or automatically restart the API after an outage.

`make docker-up` already runs `docker compose up --build`, so adding the service
is sufficient for that command to start Redis. `make redis-cli` opens the Redis
CLI inside its container.

## 2. Settings choose the address

`REDIS_URL=redis://localhost:6379/0` means:

- `redis://`: Redis protocol.
- `localhost`: server hostname when Python runs on your laptop.
- `6379`: Redis's port.
- `/0`: logical database index 0.

In a container, `localhost` refers to that container itself. Compose therefore
overrides the setting with `redis://redis:6379/0` for API and test services.
The Pydantic `Settings` class reads the setting just like existing database settings.

## 3. FastAPI owns the client lifetime

Read `app/core/redis.py` alongside `app/main.py`:

1. `lifespan=redis_lifespan` registers an async context manager with FastAPI.
2. `Redis.from_url(...)` creates the client and its internally owned connection
   pool. It does not immediately connect to the server.
3. `await client.ping()` makes the initial connection and verifies readiness.
   Startup fails if Redis cannot be reached. Socket/connect timeouts are set to
   five seconds; library retries may make total failure time longer.
4. `app.state.redis = client` exposes this instance to the app's requests.
5. `yield` hands control to FastAPI to serve requests.
6. On shutdown, `finally` clears the reference and `await client.aclose()` closes
   the client and its pool. Cleanup also runs if the startup ping fails.

`decode_responses=True` returns text for normal string reads instead of bytes.
One shared client means one pool per API process, not one TCP connection for the
whole deployment. Multiple Uvicorn worker processes each own their own client.

## 4. How later endpoints reuse it

This is an example for a later task, not an endpoint added by S5-01:

```python
from fastapi import Depends
from redis.asyncio import Redis

from app.core.redis import get_redis


@router.get("/example")
async def example(redis: Redis = Depends(get_redis)):
    await redis.set("taskflow:demo:message", "hello", ex=30)
    return {"value": await redis.get("taskflow:demo:message")}
```

`Depends(get_redis)` retrieves the existing client. `await` allows the event loop
to run other work while waiting for network I/O. It does not move computation to
another CPU or turn the operation into a durable background job. `ex=30` gives
this example key a 30-second TTL; caching and invalidation policy come later.

Import `get_redis` rather than a client variable: the client exists only during
the app lifespan. Tests can override this dependency with a fake. HTTPX's
`ASGITransport` does not automatically run lifespan; lifecycle tests explicitly
enter `app.router.lifespan_context(app)`.

## 5. Run a short demo

From `session-05-async-redis-celery`:

```bash
cp .env.example .env  # first setup only; configure JWT_SECRET_KEY
make install
make docker-up
```

In another terminal:

```bash
docker compose ps
make redis-cli
```

At the Redis prompt:

```text
PING
SET taskflow:demo:message hello EX 30
GET taskflow:demo:message
TTL taskflow:demo:message
DEL taskflow:demo:message
EXIT
```

Expected: `PONG`, `OK`, `hello`, a decreasing TTL, and a deletion count of 1
if the key has not expired. `docker compose logs api redis` shows startup.

For a persistence check, set a separate key without a TTL, restart the Redis
service, and read it again. Delete the demo key afterwards. `docker compose down`
preserves named volumes; `down -v` deletes them, including database volumes.

## 6. Verify changes

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest tests/unit/test_redis_lifecycle.py
make test
```

Run `uv run python -m scripts.demo_redis` for a repeatable real-server check.
It verifies PING, shared-client reuse, SET/GET, TTL, and shutdown, and removes
its unique demo key.

The three lifecycle tests cover reuse and normal shutdown, failed startup, and
cleanup when an exception escapes the running lifespan. They use a fake client;
the CLI demo and a real-server lifespan check verify network connectivity.

The full existing suite also needs PostgreSQL, MongoDB, and a migrated dedicated
test database. Set `TEST_DATABASE_URL` to a reachable address. When running
`make docker-test`, use `postgres` as that URL's host because pytest runs inside
a container. Do not point integration tests at production data.

## Verified result

- Full suite: **215 passed**, including the three new lifecycle tests.
- Ruff lint and formatting, mypy, and `uv lock --check`: passed.
- Compose configuration validation: passed.
- Real `redis:7-alpine` service: healthy; CLI `PING` returned `PONG`.
- `scripts.demo_redis`: shared-client reuse, SET/GET, TTL, deletion, and shutdown passed.

Local verification used an isolated PostgreSQL container named
`s5-01-redis-test-db` on host port `15432`, migrated to head, plus the existing
local MongoDB service. The ignored `.env` points `TEST_DATABASE_URL` to that
isolated database. Redis runs in the Session 5 Compose project on port `6379`.
The entire API Docker image was not built as part of these checks.

## References

- [Redis async client](https://redis.io/docs/latest/develop/clients/redis-py/async/)
- [redis-py async cleanup](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html)
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
- [Compose readiness ordering](https://docs.docker.com/compose/how-tos/startup-order/)
