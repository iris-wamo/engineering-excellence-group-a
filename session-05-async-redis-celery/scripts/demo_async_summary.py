"""Send N concurrent /tasks/summary requests in each mode and print timings.

Usage: make demo-async N=20 DELAY=0.5 (API must be running, data from make seed-rbac).
Env: BASE_URL, DEMO_USERNAME, SEED_USER_PASSWORD.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time

import httpx

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
USERNAME = os.getenv("DEMO_USERNAME", "admin")
PASSWORD = os.getenv("SEED_USER_PASSWORD", "Password123!")


async def _login(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/auth/login", data={"username": USERNAME, "password": PASSWORD}
    )
    if response.status_code != 200:
        sys.exit(
            f"Login failed ({response.status_code}): {response.text}\n"
            "Run `make migrate && make seed-rbac` and start the API with `make run`."
        )
    return response.json()["access_token"]


async def _one(
    client: httpx.AsyncClient, mode: str, delay: float | None
) -> tuple[float, dict]:
    params: dict[str, str] = {"mode": mode}
    if delay is not None:
        params["external_delay"] = str(delay)
    started = time.perf_counter()
    response = await client.get("/tasks/summary", params=params)
    response.raise_for_status()
    return (time.perf_counter() - started) * 1000, response.json()


async def _run_mode(
    client: httpx.AsyncClient, mode: str, n: int, delay: float | None
) -> None:
    started = time.perf_counter()
    results = await asyncio.gather(*(_one(client, mode, delay) for _ in range(n)))
    wall_ms = (time.perf_counter() - started) * 1000
    latencies = [r[0] for r in results]
    external = [r[1]["external"]["status"] for r in results]
    print(
        f"{mode:<9} n={n:<4} wall={wall_ms:8.0f} ms   "
        f"latency min/avg/max={min(latencies):6.0f}/"
        f"{statistics.mean(latencies):6.0f}/{max(latencies):6.0f} ms   "
        f"external ok={external.count('ok')} timeout={external.count('timeout')} "
        f"error={external.count('error')}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--n", type=int, default=int(os.getenv("N", "20")))
    parser.add_argument(
        "--delay",
        type=float,
        default=float(os.environ["DELAY"]) if os.getenv("DELAY") else None,
        help="external delay in seconds (default: server setting)",
    )
    args = parser.parse_args()

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120) as client:
        token = await _login(client)
        client.headers["Authorization"] = f"Bearer {token}"
        await _one(client, "async", 0)  # warm up connections and DB pool
        print(f"GET {BASE_URL}/tasks/summary as {USERNAME!r}")
        for mode in ("async", "blocking"):
            await _run_mode(client, mode, args.n, args.delay)


if __name__ == "__main__":
    asyncio.run(main())
