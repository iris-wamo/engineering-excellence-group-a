"""Demonstrate shared contracts and tracing without a database or running server."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from taskflow_shared.config import BaseAppConfig
from taskflow_shared.contracts import IdentifiableSchema, TimestampedSchema
from taskflow_shared.enums import SortOrder
from taskflow_shared.errors import AppError, ErrorResponse
from taskflow_shared.logging import RequestIDMiddleware, get_request_id
from taskflow_shared.pagination import PaginatedResponse, PaginationParams


class ExampleResource(IdentifiableSchema, TimestampedSchema):
    name: str


async def main() -> None:
    config = BaseAppConfig(_env_file=None)
    now = datetime.now(UTC)
    resource = ExampleResource(
        id=uuid4(), name="example", created_at=now, updated_at=now
    )
    params = PaginationParams(page=2, page_size=10)
    page = PaginatedResponse[ExampleResource](
        items=[resource], page=params.page, page_size=params.page_size, total=11
    )
    error = AppError("EXAMPLE_ERROR", "Example validation failure")

    async def endpoint(_request: Request) -> JSONResponse:
        return JSONResponse({"request_id": get_request_id()})

    application = RequestIDMiddleware(Starlette(routes=[Route("/", endpoint)]))
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://demo"
    ) as client:
        response = await client.get("/", headers={"X-Request-ID": "shared-demo-001"})

    assert response.headers["x-request-id"] == "shared-demo-001"
    assert response.json()["request_id"] == "shared-demo-001"
    assert get_request_id() is None
    print(
        json.dumps(
            {
                "environment": config.ENVIRONMENT.value,
                "sort_order": SortOrder.ASC.value,
                "offset": params.offset,
                "page": page.model_dump(mode="json"),
                "error": ErrorResponse(error=error.error).model_dump(),
                "request_id": response.headers["x-request-id"],
                "context_after_request": get_request_id(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
