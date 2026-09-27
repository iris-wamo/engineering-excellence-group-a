# Sync vs Async SQLAlchemy

## Overview

SQLAlchemy supports both synchronous and asynchronous database access.

Our application uses **async SQLAlchemy**, which fits well with FastAPI's asynchronous request handling and I/O-bound workloads.

## Sync SQLAlchemy

A synchronous setup uses:

* `create_engine()`
* `Session`
* Synchronous database drivers
* Regular `def` functions

Database operations are blocking. When the application waits for the database response, the current execution thread is blocked.

```python
engine = create_engine(DATABASE_URL)

with Session(engine) as db:
    result = db.execute(...)
```

### Benefits

* Simpler implementation
* Easier debugging and learning
* Suitable for small or low-concurrency applications
* Works well with synchronous libraries

### Limitations

* Database I/O is blocking
* Less efficient for applications handling many concurrent I/O operations

## Async SQLAlchemy

An asynchronous setup uses:

* `create_async_engine()`
* `AsyncSession`
* An async-compatible database driver
* `async def` and `await`

```python
engine = create_async_engine(DATABASE_URL)

async with AsyncSession(engine) as db:
    result = await db.execute(...)
```

While waiting for database I/O, the event loop can handle other asynchronous work.

### Benefits

* Better concurrency for I/O-bound applications
* Works naturally with FastAPI async endpoints
* Efficient when handling many simultaneous requests
* Suitable for services that perform multiple I/O operations

### Limitations

* More complex than synchronous SQLAlchemy
* Requires async-compatible drivers
* Blocking synchronous operations can reduce the benefits of async
* Developers need to understand `async`, `await`, and `AsyncSession`

## Comparison

| Aspect          | Sync                        | Async                           |
| --------------- | --------------------------- | ------------------------------- |
| Engine          | `create_engine()`           | `create_async_engine()`         |
| Session         | `Session`                   | `AsyncSession`                  |
| Endpoint        | `def`                       | `async def`                     |
| Query           | Blocking                    | Awaitable                       |
| Complexity      | Lower                       | Higher                          |
| Concurrency     | Thread/process based        | Event-loop based                |
| Best suited for | Simple/low-concurrency apps | I/O-heavy/high-concurrency apps |



## Small Endpoint Comparison

### Sync

```python
@app.get("/users")
def get_users(db: Session = Depends(get_db)):
    return db.query(User).all()
```

### Async

```python
@app.get("/users")
async def get_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User))
    return result.scalars().all()
```

## Conclusion

Async SQLAlchemy does not make individual database queries inherently faster. Its main advantage is **better utilization of application resources while waiting for I/O**.

Our application uses async SQLAlchemy because it aligns with FastAPI's asynchronous architecture and is appropriate for an I/O-bound API.


# DB Sessions, Connections, Pooling, and Closures

## Overview

SQLAlchemy uses sessions, database connections, and connection pools for database operations.

* **AsyncSession:** Manages database operations and transactions.
* **Connection:** The actual communication channel between the application and PostgreSQL.
* **Connection Pool:** Maintains reusable database connections.

## API Request Lifecycle

```text
HTTP Request
    ↓
FastAPI dependency
    ↓
AsyncSession created
    ↓
Database operation
    ↓
Connection obtained from pool
    ↓
Query executed
    ↓
Commit OR Rollback
    ↓
Session closed
    ↓
Connection returned to pool
    ↓
HTTP Response
```

## Session Dependency Pattern

A common FastAPI pattern is:

```python
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

The session is injected into endpoints using FastAPI dependency injection:

```python
async def endpoint(db: AsyncSession = Depends(get_db)):
    ...
```

The context manager ensures that the session is closed after use.

## Commit

Changes are persisted when the current transaction is committed:

```python
await db.commit()
```

The location of `commit()` depends on the application's architecture, such as repository layer in our case.

## Rollback

If a database operation fails or the transaction should be discarded:

```python
await db.rollback()
```

Rollback removes uncommitted changes from the current transaction and allows the session to be used again.

## Session Closure

Sessions should always be closed after use.

Using:

```python
async with AsyncSessionLocal() as session:
```

provides automatic cleanup.

If sessions are not closed properly, connections can remain checked out from the pool, eventually causing connection exhaustion, increased latency, or pool timeouts.

## Connection Pooling

SQLAlchemy reuses database connections through a connection pool instead of creating a new connection for every request.

Example:

```python
create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
)
```

* `pool_size`: Number of persistent connections maintained by the pool.
* `max_overflow`: Additional connections allowed when the pool is fully utilized.
* `pool_timeout`: Maximum time to wait for an available connection.

Pool configuration should consider application traffic and PostgreSQL connection limits.

## Key Takeaway

The **session** manages database work and transactions, the **connection** communicates with PostgreSQL, and the **pool** manages reusable connections.

Proper **commit, rollback, and session cleanup** are essential for reliable database operation.
