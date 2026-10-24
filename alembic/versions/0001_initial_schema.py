"""Initial schema with pg_trgm, gates, devices, detections, media, corrections, counters, health, audit

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-18 14:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0. Enable pg_trgm extension if on PostgreSQL
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # 1. Gates table
    op.create_table(
        "gates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("timezone", sa.String(length=50), server_default="Asia/Kolkata", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. Devices table
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gate_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["gate_id"], ["gates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_devices_api_key_hash"), "devices", ["api_key_hash"], unique=False)

    # 3. Users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="viewer", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("failed_logins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    # 4. Daily Counters table
    op.create_table(
        "daily_counters",
        sa.Column("gate_id", sa.Integer(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("last_no", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["gate_id"], ["gates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("gate_id", "local_date", name="pk_daily_counters"),
    )

    # 5. Detections table
    op.create_table(
        "detections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("event_uid", sa.String(length=128), nullable=False),
        sa.Column("gate_id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.String(length=50), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("day_serial", sa.Integer(), nullable=False),
        sa.Column("plate_raw", sa.String(length=64), nullable=False),
        sa.Column("plate", sa.String(length=64), nullable=False),
        sa.Column("plate_valid", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("plate_conf", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("vehicle_type", sa.String(length=20), server_default="other", nullable=False),
        sa.Column("vehicle_color", sa.String(length=50), nullable=True),
        sa.Column("load_type", sa.String(length=20), server_default="unknown", nullable=False),
        sa.Column("load_conf", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("load_source", sa.String(length=20), server_default="auto", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="needs_review", nullable=False),
        sa.Column("media_ready", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("clip_ref", sa.JSON(), nullable=True),
        sa.Column("raw_event", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["gate_id"], ["gates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_uid", name="uq_detections_event_uid"),
    )
    op.create_index("ix_detections_plate", "detections", ["plate"], unique=False)
    op.create_index("ix_detections_captured_at_desc", "detections", [sa.text("captured_at DESC")], unique=False)
    op.create_index("ix_detections_veh_load", "detections", ["vehicle_type", "load_type"], unique=False)

    # GIN trigram index on plate in PostgreSQL
    if bind.dialect.name == "postgresql":
        op.execute("CREATE INDEX IF NOT EXISTS ix_detections_plate_trgm ON detections USING gin (plate gin_trgm_ops);")

    # 6. Media table
    op.create_table(
        "media",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("detection_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("object_key", sa.String(length=255), nullable=True),
        sa.Column("bytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["detection_id"], ["detections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_detection_id", "media", ["detection_id"], unique=False)

    # 7. Corrections table
    op.create_table(
        "corrections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("detection_id", sa.UUID(), nullable=False),
        sa.Column("field", sa.String(length=50), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["detection_id"], ["detections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_corrections_detection_id", "corrections", ["detection_id"], unique=False)

    # 8. Health table
    op.create_table(
        "health",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("camera_a_ok", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("camera_b_ok", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("disk_used_pct", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("queue_depth", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ups_on_battery", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_device_id", "health", ["device_id"], unique=False)

    # 9. Audit Views table
    op.create_table(
        "audit_views",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("detection_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["detection_id"], ["detections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_views_detection_id", "audit_views", ["detection_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_detections_plate_trgm;")

    op.drop_table("audit_views")
    op.drop_table("health")
    op.drop_table("corrections")
    op.drop_table("media")
    op.drop_table("detections")
    op.drop_table("daily_counters")
    op.drop_table("users")
    op.drop_table("devices")
    op.drop_table("gates")
