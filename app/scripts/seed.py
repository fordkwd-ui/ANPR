"""Database seed script: initializes admin user, gate, and device with printed API key."""
import asyncio
import secrets
from sqlalchemy import select
from app.core.security import hash_api_key, hash_password
from app.db.session import async_session_factory
from app.models.gate import Device, Gate
from app.models.user import User, UserRole


async def seed(session_maker=None) -> None:
    factory = session_maker or async_session_factory
    print("=" * 60)
    print("🌱 SEEDING VEHICLE GATE MONITORING SYSTEM")
    print("=" * 60)

    # Ensure tables exist
    from app.db.base import Base
    import app.models  # register all models
    from app.db.session import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as db:
        # 1. Admin User
        admin_res = await db.execute(select(User).where(User.username == "admin"))
        admin = admin_res.scalar_one_or_none()
        if not admin:
            admin = User(
                username="admin",
                password_hash=hash_password("AdminGatePassword2026!"),
                role=UserRole.ADMIN,
                active=True,
            )
            db.add(admin)
            print("👤 Created Admin User:     username='admin' | password='AdminGatePassword2026!'")
        else:
            print("ℹ️ Admin user already exists.")

        # 2. Reviewer User
        reviewer_res = await db.execute(select(User).where(User.username == "reviewer"))
        if not reviewer_res.scalar_one_or_none():
            reviewer = User(
                username="reviewer",
                password_hash=hash_password("ReviewerPass2026!"),
                role=UserRole.REVIEWER,
                active=True,
            )
            db.add(reviewer)
            print("👤 Created Reviewer User:  username='reviewer' | password='ReviewerPass2026!'")

        # 3. Viewer User
        viewer_res = await db.execute(select(User).where(User.username == "viewer"))
        if not viewer_res.scalar_one_or_none():
            viewer = User(
                username="viewer",
                password_hash=hash_password("ViewerPass2026!"),
                role=UserRole.VIEWER,
                active=True,
            )
            db.add(viewer)
            print("👤 Created Viewer User:    username='viewer' | password='ViewerPass2026!'")

        # 4. Gate
        gate_res = await db.execute(select(Gate).limit(1))
        gate = gate_res.scalar_one_or_none()
        if not gate:
            gate = Gate(name="Pine Valley Forest Gate", timezone="Asia/Kolkata")
            db.add(gate)
            await db.flush()
            print(f"🌲 Created Forest Gate:     name='{gate.name}' (id={gate.id}) | timezone='{gate.timezone}'")
        else:
            print(f"ℹ️ Gate already exists:    id={gate.id} ({gate.name})")

        # 5. Device with Edge API Key
        import os
        raw_api_key = os.getenv("DEVICE_API_KEY") or f"gate_key_{secrets.token_urlsafe(32)}"
        key_hash = hash_api_key(raw_api_key)

        device_res = await db.execute(select(Device).where(Device.gate_id == gate.id).limit(1))
        device = device_res.scalar_one_or_none()
        if not device:
            device = Device(
                gate_id=gate.id,
                name="Edge GateBox Alpha (Camera A/B)",
                api_key_hash=key_hash,
            )
            db.add(device)
            await db.commit()
            print(f"📷 Created Gate Device:    name='{device.name}' (id={device.id})")
            print("=" * 60)
            print("🔑 PRINTED EDGE API KEY (Keep this safe for gate box!):")
            print(f"   X-API-Key: {raw_api_key}")
            print("=" * 60)
        else:
            await db.commit()
            print(f"ℹ️ Device already exists:  id={device.id} ({device.name})")
            print("=" * 60)

    print("✅ Seeding completed successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
