# S5-06: Redis Pub/Sub producer and subscriber

Issue: [#42](https://github.com/iris-wamo/engineering-excellence-group-a/issues/42)

## How it works

- **Producer:** the API. After a task is assigned or changes status (and the DB
  commit succeeds), `publish_task_event()` from S5-05 runs
  `PUBLISH taskflow:events:task <event JSON>`.
- **Subscriber:** `app/events/pubsub_consumer.py`. It runs
  `SUBSCRIBE taskflow:events:task` and logs every event it receives.

```bash
make run               # terminal 1: API
make pubsub-consumer   # terminal 2: subscriber (Ctrl+C to stop)
```

Each event is logged on one line:

```
INFO received task.status_changed v1 event_id=... task=... actor=... data={'from_status': 'todo', 'to_status': 'in_progress'}
```

Payloads that aren't a valid `TaskEvent` are logged as a warning and skipped, so
one bad message can't stop the subscriber.

## Demo: the event is lost

One task, logged in as `alice`. Three status changes:

| Step | Subscriber | API call | Result |
| --- | --- | --- | --- |
| 1 | running | todo → in_progress | received |
| 2 | **stopped** (`PUBSUB NUMSUB` = 0) | in_progress → in_review | **lost** |
| 3 | restarted | in_review → done | received |

API log: all three events were published.

```
INFO:     event task.status_changed 60551256-... published   <- step 1
INFO:     event task.status_changed 50fbf316-... published   <- step 2
INFO:     event task.status_changed 295d6297-... published   <- step 3
```

Subscriber, first run:

```
INFO subscribed to taskflow:events:task, waiting for events
INFO received task.status_changed v1 event_id=60551256-... data={'from_status': 'todo', 'to_status': 'in_progress'}
```

Subscriber after restart:

```
INFO subscribed to taskflow:events:task, waiting for events
INFO received task.status_changed v1 event_id=295d6297-... data={'from_status': 'in_review', 'to_status': 'done'}
```

Event `50fbf316` (in_progress → in_review) never shows up. The restarted
subscriber doesn't get it, and there's no way to ask Redis for it.

You can see this directly: `PUBLISH` returns how many subscribers got the message.

```
$ redis-cli PUBLISH taskflow:events:task '{"test": 1}'
(integer) 0        <- nobody was listening, so the message is gone
```

## Why Pub/Sub has no durability, ack or replay

Redis Pub/Sub is a broadcast, not a queue. When a message is published, Redis
sends it to the clients subscribed **at that moment** and then forgets it.

- **No durability:** the message is never stored. Nothing is written to memory or
  disk, so a subscriber that is down, restarting or reconnecting misses it.
- **No ack:** a subscriber can't say "I processed this". If it crashes halfway
  through, Redis doesn't know and won't send it again.
- **No replay:** there's no history and no message id, so a new or restarted
  subscriber can't ask for "everything since X".
- **Slow subscribers** can be disconnected if their output buffer fills up, and
  they lose those messages too.

That is what "fire-and-forget" means: the publisher sends and moves on, and
doesn't know or care if anyone received it.

## When that's acceptable

Pub/Sub is fine when losing a message is okay, because the data is also
somewhere else or will be refreshed soon:

- live UI updates (refresh a dashboard, "someone is typing")
- cache invalidation hints across servers, where entries also have a TTL
- metrics, debug or monitoring streams
- anything where the client reloads the real state from the database anyway

It's **not** acceptable when every event must be handled: sending a notification
email, billing, audit logs, or syncing another system. For those, use Redis
Streams with consumer groups (S5-07), which store messages, track acks and let
a restarted consumer catch up. A message broker like Kafka or RabbitMQ also works.

Note: even with Streams, S5-05 publishes after the commit, so an event can still
be lost if the API crashes between the commit and the publish. The outbox
pattern fixes that.

## Tests

`tests/unit/test_pubsub_consumer.py`:

- a valid event is parsed and logged with its type, version and `event_id`
- an invalid payload is skipped with a warning
- with a real Redis: an event published before the subscriber starts gets
  `PUBLISH = 0` and is never logged, while an event published after it subscribes
  is received (skipped if Redis isn't running)
