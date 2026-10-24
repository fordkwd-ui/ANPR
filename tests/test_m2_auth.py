"""Milestone 2 tests: Argon2, JWT Auth, Login Lockout, Role Matrix, and Device API Key."""
from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_api_key,
    hash_password,
    verify_password,
)
from app.models.gate import Device, Gate
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_argon2_password_hashing():
    """Verifies Argon2 hashing and verification."""
    password = "SuperForestGateSecure2026!"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


@pytest.mark.asyncio
async def test_login_success_and_refresh(async_client: AsyncClient, db_session: AsyncSession):
    """Verifies successful login, token issuance, and token refresh."""
    user = User(
        username="gate_viewer",
        password_hash=hash_password("password123"),
        role=UserRole.VIEWER,
        active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Login
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"username": "gate_viewer", "password": "password123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["username"] == "gate_viewer"
    assert data["user"]["role"] == "viewer"

    access_token = data["access_token"]
    refresh_token = data["refresh_token"]

    # Access /auth/me
    me_resp = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "gate_viewer"

    # Refresh token
    refresh_resp = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_resp.status_code == 200
    new_access_token = refresh_resp.json()["access_token"]
    assert new_access_token is not None


@pytest.mark.asyncio
async def test_login_lockout_after_5_attempts(async_client: AsyncClient, db_session: AsyncSession):
    """Verifies that 5 failed logins triggers a 15-minute lockout."""
    user = User(
        username="lockout_user",
        password_hash=hash_password("correct_pass"),
        role=UserRole.VIEWER,
        active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # 4 failed attempts -> 401
    for _ in range(4):
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"username": "lockout_user", "password": "wrong_password"},
        )
        assert resp.status_code == 401

    # 5th failed attempt -> locks account and returns 401
    resp5 = await async_client.post(
        "/api/v1/auth/login",
        json={"username": "lockout_user", "password": "wrong_password"},
    )
    assert resp5.status_code == 401

    # 6th attempt (even with CORRECT password) -> 403 Forbidden (locked)
    resp6 = await async_client.post(
        "/api/v1/auth/login",
        json={"username": "lockout_user", "password": "correct_pass"},
    )
    assert resp6.status_code == 403
    assert "locked" in resp6.json()["detail"].lower()


@pytest.mark.asyncio
async def test_expired_token_rejected(async_client: AsyncClient, db_session: AsyncSession):
    """Verifies that expired access and refresh tokens are rejected."""
    user = User(
        username="expire_user",
        password_hash=hash_password("pass"),
        role=UserRole.VIEWER,
        active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Generate token expired 1 minute ago
    expired_token = create_access_token(
        subject=user.username,
        role=user.role.value,
        user_id=user.id,
        expires_delta=timedelta(minutes=-1),
    )

    resp = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()

    # Expired refresh token
    expired_refresh = create_refresh_token(
        subject=user.username,
        user_id=user.id,
        expires_delta=timedelta(days=-1),
    )
    refresh_resp = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": expired_refresh},
    )
    assert refresh_resp.status_code == 401
    assert "expired" in refresh_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_role_matrix_and_user_crud(async_client: AsyncClient, db_session: AsyncSession):
    """Verifies role permissions: viewer cannot manage users, admin can."""
    admin_user = User(
        username="admin_user",
        password_hash=hash_password("adminpass"),
        role=UserRole.ADMIN,
        active=True,
    )
    viewer_user = User(
        username="regular_viewer",
        password_hash=hash_password("viewerpass"),
        role=UserRole.VIEWER,
        active=True,
    )
    db_session.add_all([admin_user, viewer_user])
    await db_session.commit()
    await db_session.refresh(admin_user)
    await db_session.refresh(viewer_user)

    viewer_token = create_access_token(viewer_user.username, viewer_user.role.value, viewer_user.id)
    admin_token = create_access_token(admin_user.username, admin_user.role.value, admin_user.id)

    # Viewer tries to access GET /api/v1/users -> 403 Forbidden
    v_resp = await async_client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert v_resp.status_code == 403

    # Admin accesses GET /api/v1/users -> 200 OK
    a_resp = await async_client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert a_resp.status_code == 200
    assert len(a_resp.json()) >= 2

    # Admin creates new user
    create_resp = await async_client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "username": "new_reviewer",
            "password": "reviewer_pass_123",
            "role": "reviewer",
        },
    )
    assert create_resp.status_code == 201
    new_user_data = create_resp.json()
    assert new_user_data["username"] == "new_reviewer"
    assert new_user_data["role"] == "reviewer"


@pytest.mark.asyncio
async def test_device_api_key_authentication(async_client: AsyncClient, db_session: AsyncSession):
    """Verifies device lookup via SHA-256 hashed API key in dependencies."""
    from app.core.dependencies import get_current_device

    gate = Gate(name="North Forest Gate", timezone="Asia/Kolkata")
    db_session.add(gate)
    await db_session.flush()

    raw_api_key = "gatebox-test-secret-key-xyz"
    key_hash = hash_api_key(raw_api_key)

    device = Device(
        gate_id=gate.id,
        name="Gate Box Mini PC 1",
        api_key_hash=key_hash,
    )
    db_session.add(device)
    await db_session.commit()
    await db_session.refresh(device)

    # Directly test dependency function via header
    resolved_device = await get_current_device(x_api_key=raw_api_key, db=db_session)
    assert resolved_device.id == device.id
    assert resolved_device.last_seen_at is not None

    # Test via query parameter (direct camera push without custom headers)
    resolved_query = await get_current_device(api_key_query=raw_api_key, db=db_session)
    assert resolved_query.id == device.id

    # Invalid key
    with pytest.raises(Exception):
        await get_current_device(x_api_key="wrong-key", db=db_session)
