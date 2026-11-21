"""Exercise the shared client against real Redis: uv run python -m scripts.demo_redis."""

import asyncio
from time import monotonic
from uuid import uuid4

from starlette.requests import Request

from app.core.redis import get_redis
from app.main import app


async def main() -> None:
    key = f"taskflow:demo:{uuid4()}"
    async with app.router.lifespan_context(app):
        request = Request({"type": "http", "app": app})
        client = get_redis(request)
        assert get_redis(request) is client
        try:
            assert await client.ping()
            await client.set(key, "hello", ex=30)
            assert await client.get(key) == "hello"
            ttl = await client.ttl(key)
            assert 0 < ttl <= 30
            print(f"PING OK; shared client reused; SET/GET OK; TTL={ttl}s")
            # Regression: the former 5s socket timeout interrupted this 8s wait.
            started = monotonic()
            async with asyncio.timeout(15):
                result = await client.blpop([f"{key}:empty"], timeout=8)
            elapsed = monotonic() - started
            assert result is None
            assert elapsed >= 8
            assert await client.ping()
            print(f"BLPOP waited {elapsed:.1f}s and returned None; client still usable")
        finally:
            await client.delete(key)
    assert app.state.redis is None
    print("Demo key deleted; lifespan shutdown completed")


if __name__ == "__main__":
    asyncio.run(main())
