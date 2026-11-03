"""Secure-by-default guard: every route except the public allowlist needs a token.

Security is attached with router-level dependencies, not middleware, so this
test is what stops a new router or route from shipping unprotected. Routes are
enumerated from the public OpenAPI schema: a route that depends on the bearer
scheme is listed there with ``security`` (Swagger's lock icon).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

PUBLIC_ROUTES = {
    ("POST", "/auth/signup"),
    ("POST", "/auth/login"),
    ("GET", "/health"),
}


def _all_routes() -> dict[tuple[str, str], dict]:
    return {
        (method.upper(), path): operation
        for path, operations in app.openapi()["paths"].items()
        for method, operation in operations.items()
    }


def _protected_routes() -> list[tuple[str, str]]:
    return sorted(set(_all_routes()) - PUBLIC_ROUTES)


def test_public_allowlist_matches_real_routes():
    """A renamed public route must not silently drop out of the allowlist."""
    assert set(_all_routes()) >= PUBLIC_ROUTES


def test_public_routes_need_no_token():
    for key in PUBLIC_ROUTES:
        assert "security" not in _all_routes()[key], key


@pytest.mark.parametrize(("method", "path"), _protected_routes())
def test_every_non_public_route_declares_bearer_security(method, path):
    operation = _all_routes()[(method, path)]
    assert {"OAuth2PasswordBearer": []} in operation.get("security", []), (
        f"{method} {path} is not protected; attach get_current_user to its router"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), _protected_routes())
async def test_every_non_public_route_returns_401_without_token(method, path):
    url = path
    for param in ("task_id", "project_id", "user_id"):
        url = url.replace("{" + param + "}", str(uuid.uuid4()))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, url, json={})

    assert response.status_code == 401, (method, path, response.text)
    assert response.json()["detail"]["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"
