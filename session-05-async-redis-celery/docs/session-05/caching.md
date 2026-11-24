# S5-04: Caching the task summary in Redis

Issue: [#40](https://github.com/iris-wamo/engineering-excellence-group-a/issues/40)

## How it works

`GET /tasks/summary` (default `mode=async`) is cached per user:

| | |
| --- | --- |
| Key | `taskflow:v1:summary:user:{user_id}` |
| Value | the summary response as JSON |
| TTL | `SUMMARY_CACHE_TTL_SECONDS`, default 60 |
| Header | `X-Cache: HIT` or `X-Cache: MISS` |
| Log | `summary cache HIT user=...` / `summary cache MISS user=...` |

Flow: `GET key` → on a hit, return it. On a miss, compute the summary, then
`SET key value EX 60`.

Requests that are only for the S5-03 demo are never cached: `mode=blocking`,
`external_delay`, `external_fail` or `cache=false`. `make demo-async` sends
`cache=false` so its timings still compare real work.

The key is per user because the summary depends on who asks: admins count all
tasks, everyone else only their projects, and `assigned_to_me` is personal.
`v1` lets us change the cached shape later without reading old entries.

## Invalidation strategy

After a task is created, assigned, has its status changed, or gets a new due
date, the route calls `invalidate_summary_cache(user_ids)`. This runs after the
service has committed, so a reader can't cache the old data again before the
write is visible.

`user_ids` = members of the task's project + all admins, i.e. everyone whose
summary includes that task. Users outside the project keep their cache. This is
delete-on-write: we don't update the cached value, we just remove it, and the
next read rebuilds it.

## Stale-cache window

A user can still see old numbers in these cases:

- **Overdue changes by time alone.** A task becomes overdue when its due date
  passes, without any write, so nothing invalidates the cache. The count can be
  up to one TTL (60s) late.
- **Membership changes.** Adding or removing a project member doesn't invalidate
  that user's summary. It fixes itself when the TTL runs out.
- **Redis error during invalidation.** It's logged as a warning, and the old
  entry lives until its TTL ends.
- **Race.** A read that started before a commit can finish after the invalidation
  and store old data. The TTL limits this to 60s.

So the worst case is always "at most one TTL old". That is fine for a dashboard
count, and the reason the TTL should stay short.

## If Redis is down

Every Redis call has a short timeout (`SUMMARY_CACHE_TIMEOUT_SECONDS`, 0.5s) and
catches Redis/connection errors. The endpoint then computes the summary directly,
returns `X-Cache: MISS`, and logs a warning. Tested by stopping Redis while the
API was running:

```
$ redis-cli shutdown nosave
$ curl -i .../tasks/summary
HTTP/1.1 200 OK            (0.31s)
x-cache: MISS

WARNING:     summary cache: Redis unavailable (network:ConnectionError), computing directly
WARNING:     summary cache: could not store summary (network:ConnectionError)
```

Note: the app still needs Redis at startup (S5-01 pings it in the lifespan).

## What not to cache

- **Partial summaries.** If the external call timed out or failed, we don't store
  the result. Otherwise one slow call would show `"timeout"` for a full minute.
- **Demo/override requests** (see above), since they aren't the real answer.
- **Anything shared between users** under one key, since each user sees
  different data.
- **Data that must be exact right now**, like the task list or task details used
  to make changes. Those always read PostgreSQL. The summary is fine to cache
  only because a few seconds late is acceptable for counts.
- **Secrets or tokens.** Redis is not the place for them.

## redis-cli evidence

Logged in as `alice`, called the summary twice, changed a task's due date, then
called it again.

**KEYS and TTL** after the first request:

```
$ redis-cli KEYS 'taskflow:v1:summary:*'
taskflow:v1:summary:user:a2b036cf-3c49-53a1-ac33-a99742e94e44
$ redis-cli TTL taskflow:v1:summary:user:a2b036cf-3c49-53a1-ac33-a99742e94e44
60
```

**MONITOR** during the whole flow (JSON values shortened):

```
"GET" "taskflow:v1:summary:user:a2b0..."              <- 1st request: MISS
"SET" "taskflow:v1:summary:user:a2b0..." "{...\"overdue\":0...}" "EX" "60"
"GET" "taskflow:v1:summary:user:a2b0..."              <- 2nd request: HIT
"DEL" "taskflow:v1:summary:user:a2b0..." "...:9f80..." "...:892b..." "...:63b2..."
                                                       <- PATCH /tasks/{id}: alice, project members, admins
"GET" "taskflow:v1:summary:user:a2b0..."              <- 3rd request: MISS
"SET" "taskflow:v1:summary:user:a2b0..." "{...\"overdue\":1...}" "EX" "60"
```

**API log:**

```
INFO:     summary cache MISS user=a2b036cf-...
INFO:     summary cache HIT user=a2b036cf-...
INFO:     summary cache: invalidated 4 user(s)
INFO:     summary cache MISS user=a2b036cf-...
```

The response headers matched: `MISS`, `HIT`, then `MISS` after the update, and
`overdue` went from 0 to 1.

To try it yourself:

```bash
make redis-cli            # then: KEYS taskflow:v1:summary:*  /  TTL <key>  /  MONITOR
```

## Tests

- `tests/integration/test_summary_cache.py`: miss then hit, TTL expiry (TTL set
  to 1s), invalidation, Redis down and Redis missing both fall back with a
  warning, partial summaries not cached, demo requests skip the cache, key format.
- `tests/auth/test_summary_cache_invalidation.py` (test DB): a status change
  turns the next read into a MISS for project members while a user outside the
  project keeps his HIT, and create/assign also invalidate.

These tests use the Redis at `REDIS_URL` and are skipped if it isn't running
(CI has a Redis service).
