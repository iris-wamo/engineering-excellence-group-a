"""Exercise the shared client against real Redis: uv run python -m scripts.demo_redis."""

import asyncio
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
        finally:
            await client.delete(key)
    assert app.state.redis is None
    print("Demo key deleted; lifespan shutdown completed")


if __name__ == "__main__":
    asyncio.run(main())
