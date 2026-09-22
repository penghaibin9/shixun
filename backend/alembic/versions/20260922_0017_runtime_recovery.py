"""add durable runtime recovery actions

Revision ID: 20260922_0017
Revises: 20260922_0016
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0017"
down_revision = "20260922_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runtime_request", sa.Column("provision_owner", sa.String(length=64), nullable=True))
    op.add_column("runtime_request", sa.Column("provision_lease_expires_at", sa.DateTime(), nullable=True))
    op.add_column("runtime_queue", sa.Column("processing_owner", sa.String(length=36), nullable=True))
    op.add_column("runtime_queue", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
    op.add_column("runtime_instance_group", sa.Column("provider_generation", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("runtime_instance_group", sa.Column("cleanup_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("runtime_instance_group", sa.Column("cleanup_not_before", sa.DateTime(), nullable=True))
    op.add_column("runtime_instance_group", sa.Column("cleanup_intent", sa.String(length=32), nullable=True))
    op.add_column("runtime_instance_group", sa.Column("cleanup_owner", sa.String(length=64), nullable=True))
    op.add_column("runtime_instance_group", sa.Column("cleanup_lease_expires_at", sa.DateTime(), nullable=True))
    op.add_column("runtime_instance_group", sa.Column("cleanup_error_code", sa.String(length=64), nullable=True))
    op.add_column("runtime_instance_group", sa.Column("cleanup_error_message", sa.String(length=512), nullable=True))
    op.create_table(
        "runtime_admin_action",
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("owner_token", sa.String(length=64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("error_status_code", sa.Integer(), nullable=True),
        sa.Column("error_details_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("action_id"),
        sa.UniqueConstraint("actor_user_id", "idempotency_key", name="uq_runtime_admin_action_actor_key"),
    )
    op.create_index("ix_runtime_admin_action_type_status", "runtime_admin_action", ["action_type", "status", "updated_at"])
    op.create_table(
        "runtime_cleanup_task",
        sa.Column("cleanup_task_id", sa.String(length=36), nullable=False),
        sa.Column("runtime_group_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=36), nullable=False),
        sa.Column("provider_group_id", sa.String(length=128), nullable=False),
        sa.Column("provider_generation", sa.Integer(), nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("not_before", sa.DateTime(), nullable=True),
        sa.Column("processing_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["infra_node.node_id"], name="fk_runtime_cleanup_node", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("cleanup_task_id"),
        sa.UniqueConstraint("node_id", "provider_group_id", "intent", name="uq_runtime_cleanup_target"),
    )
    op.create_index("ix_runtime_cleanup_status_due", "runtime_cleanup_task", ["status", "not_before"])


def downgrade() -> None:
    op.drop_index("ix_runtime_cleanup_status_due", table_name="runtime_cleanup_task")
    op.drop_table("runtime_cleanup_task")
    op.drop_index("ix_runtime_admin_action_type_status", table_name="runtime_admin_action")
    op.drop_table("runtime_admin_action")
    op.drop_column("runtime_queue", "lease_expires_at")
    op.drop_column("runtime_queue", "processing_owner")
    op.drop_column("runtime_request", "provision_lease_expires_at")
    op.drop_column("runtime_request", "provision_owner")
    op.drop_column("runtime_instance_group", "cleanup_error_message")
    op.drop_column("runtime_instance_group", "cleanup_error_code")
    op.drop_column("runtime_instance_group", "cleanup_not_before")
    op.drop_column("runtime_instance_group", "cleanup_lease_expires_at")
    op.drop_column("runtime_instance_group", "cleanup_owner")
    op.drop_column("runtime_instance_group", "cleanup_intent")
    op.drop_column("runtime_instance_group", "cleanup_attempts")
    op.drop_column("runtime_instance_group", "provider_generation")
