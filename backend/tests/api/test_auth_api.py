"""Camada 3 — contrato HTTP de /auth e guardas JWT (fluxo real, sem override de user)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models.user import User

pytestmark = pytest.mark.api


async def test_register_returns_201_and_user_response(client, db_session) -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"register-{suffix}@example.com"

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "secretpass",
            "full_name": "New User",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email
    assert body["full_name"] == "New User"
    assert body["is_active"] is True
    assert "id" in body
    assert "created_at" in body

    # Mesma transação: registro visível na db_session da fixture.
    result = await db_session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    assert user is not None
    assert str(user.id) == body["id"]


async def test_register_duplicate_email_returns_400(client, db_session) -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"dup-{suffix}@example.com"
    user = User(
        email=email,
        hashed_password=hash_password("secretpass"),
        full_name="Existing",
    )
    db_session.add(user)
    await db_session.flush()

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "secretpass",
            "full_name": "Duplicate",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "secretpass", "full_name": "Bad"},
        {"email": "valid@example.com", "full_name": "No Password"},
        {"password": "secretpass", "full_name": "No Email"},
    ],
)
async def test_register_invalid_payload_returns_422(client, payload: dict) -> None:
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


async def test_login_valid_credentials_returns_token(client, db_session) -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"login-{suffix}@example.com"
    password = "secretpass"
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name="Login User",
    )
    db_session.add(user)
    await db_session.flush()

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


async def test_login_wrong_password_returns_401(client, db_session) -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"wrongpw-{suffix}@example.com"
    user = User(
        email=email,
        hashed_password=hash_password("correct"),
        full_name="User",
    )
    db_session.add(user)
    await db_session.flush()

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


async def test_login_unknown_user_returns_401(client) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "secretpass"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


async def test_protected_endpoint_without_header_returns_401(client) -> None:
    response = await client.get("/api/v1/agents/")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


async def test_protected_endpoint_invalid_token_returns_401(client) -> None:
    response = await client.get(
        "/api/v1/agents/",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


async def test_login_then_jwt_access_agents_returns_200(client, db_session) -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"jwt-smoke-{suffix}@example.com"
    password = "secretpass"
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name="JWT Smoke",
    )
    db_session.add(user)
    await db_session.flush()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    agents = await client.get(
        "/api/v1/agents/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert agents.status_code == 200
    assert isinstance(agents.json(), list)
