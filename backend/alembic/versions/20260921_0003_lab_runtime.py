"""create lab runtime and infrastructure tables

Revision ID: 20260921_0004
Revises: 20260921_0003
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0004"
down_revision = "20260921_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("infra_node",
        sa.Column("node_id", sa.String(36), primary_key=True), sa.Column("name", sa.String(96), nullable=False),
        sa.Column("agent_url", sa.String(255), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("scheduling_paused", sa.Boolean(), nullable=False), sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("labels_json", sa.JSON(), nullable=False), sa.Column("cpu_total", sa.Float(), nullable=False),
        sa.Column("memory_total_mb", sa.Integer(), nullable=False), sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.UniqueConstraint("name", name="uq_infra_node_name"))
    op.create_index("ix_infra_node_schedulable", "infra_node", ["status", "scheduling_paused"])
    op.create_table("infra_node_heartbeat",
        sa.Column("heartbeat_id", sa.String(36), primary_key=True), sa.Column("node_id", sa.String(36), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False), sa.Column("cpu_available", sa.Float(), nullable=False),
        sa.Column("memory_available_mb", sa.Integer(), nullable=False), sa.Column("running_groups", sa.Integer(), nullable=False),
        sa.Column("image_digests_json", sa.JSON(), nullable=False), sa.Column("detail_json", sa.JSON(), nullable=False))
    op.create_index("ix_heartbeat_node_time", "infra_node_heartbeat", ["node_id", "observed_at"])
    op.create_table("infra_image",
        sa.Column("image_id", sa.String(36), primary_key=True), sa.Column("name", sa.String(160), nullable=False),
        sa.Column("tag", sa.String(96), nullable=False), sa.Column("digest", sa.String(71), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False), sa.Column("scan_status", sa.String(24), nullable=False),
        sa.Column("startup_check_status", sa.String(24), nullable=False), sa.Column("teaching_validation_status", sa.String(24), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("digest", name="uq_infra_image_digest"))
    op.create_index("ix_infra_image_enabled", "infra_image", ["enabled"])
    op.create_table("infra_image_validation",
        sa.Column("validation_id", sa.String(36), primary_key=True), sa.Column("image_id", sa.String(36), nullable=False),
        sa.Column("validation_type", sa.String(32), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("detail_json", sa.JSON(), nullable=False), sa.Column("validated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_image_validation_image_time", "infra_image_validation", ["image_id", "validated_at"])
    op.create_table("runtime_request",
        sa.Column("runtime_request_id", sa.String(36), primary_key=True), sa.Column("lab_release_id", sa.String(36), nullable=False),
        sa.Column("lab_version_id", sa.String(36), nullable=False), sa.Column("course_id", sa.String(36), nullable=True),
        sa.Column("class_id", sa.String(36), nullable=True), sa.Column("student_id", sa.String(36), nullable=True),
        sa.Column("mode", sa.String(24), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("requested_by", sa.String(36), nullable=False), sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("spec_snapshot_json", sa.JSON(), nullable=False), sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False), sa.UniqueConstraint("requested_by", "idempotency_key", name="uq_runtime_request_actor_key"))
    op.create_index("ix_runtime_request_subject", "runtime_request", ["student_id", "created_at"])
    op.create_index("ix_runtime_request_status", "runtime_request", ["status"])
    op.create_table("runtime_queue",
        sa.Column("queue_id", sa.String(36), primary_key=True), sa.Column("runtime_request_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("not_before", sa.DateTime(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(), nullable=False), sa.UniqueConstraint("runtime_request_id", name="uq_runtime_queue_request"))
    op.create_index("ix_runtime_queue_state_priority", "runtime_queue", ["status", "priority", "enqueued_at"])
    op.create_table("runtime_instance_group",
        sa.Column("runtime_group_id", sa.String(36), primary_key=True), sa.Column("runtime_request_id", sa.String(36), nullable=False),
        sa.Column("node_id", sa.String(36), nullable=False), sa.Column("provider_group_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("scheduler_score", sa.Float(), nullable=False),
        sa.Column("scheduler_reason", sa.String(512), nullable=False), sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("destroyed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("runtime_request_id", name="uq_runtime_group_request"))
    op.create_index("ix_runtime_group_status", "runtime_instance_group", ["status"])
    op.create_table("runtime_instance",
        sa.Column("runtime_instance_id", sa.String(36), primary_key=True), sa.Column("runtime_group_id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=True), sa.Column("node_key", sa.String(64), nullable=False),
        sa.Column("role", sa.String(64), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True), sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True))
    op.create_index("ix_runtime_instance_student_status", "runtime_instance", ["student_id", "status"])
    op.create_index("ix_runtime_instance_group", "runtime_instance", ["runtime_group_id"])
    op.create_table("runtime_container",
        sa.Column("runtime_container_id", sa.String(36), primary_key=True), sa.Column("runtime_instance_id", sa.String(36), nullable=False),
        sa.Column("provider_container_id", sa.String(128), nullable=False), sa.Column("image_digest", sa.String(71), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("provider_container_id", name="uq_runtime_provider_container"))
    op.create_index("ix_runtime_container_instance", "runtime_container", ["runtime_instance_id"])
    op.create_table("runtime_network",
        sa.Column("runtime_network_id", sa.String(36), primary_key=True), sa.Column("runtime_group_id", sa.String(36), nullable=False),
        sa.Column("network_key", sa.String(64), nullable=False), sa.Column("provider_network_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("isolation_checks_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("runtime_group_id", "network_key", name="uq_runtime_network_key"))
    op.create_table("runtime_event",
        sa.Column("runtime_event_id", sa.String(36), primary_key=True), sa.Column("runtime_instance_id", sa.String(36), nullable=True),
        sa.Column("runtime_group_id", sa.String(36), nullable=True), sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False), sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False))
    op.create_index("ix_runtime_event_instance_time", "runtime_event", ["runtime_instance_id", "occurred_at"])
    op.create_table("runtime_resource_usage",
        sa.Column("usage_id", sa.String(36), primary_key=True), sa.Column("runtime_instance_id", sa.String(36), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=False), sa.Column("memory_used_mb", sa.Integer(), nullable=False),
        sa.Column("network_rx_bytes", sa.BigInteger(), nullable=False), sa.Column("network_tx_bytes", sa.BigInteger(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False))
    op.create_index("ix_runtime_usage_instance_time", "runtime_resource_usage", ["runtime_instance_id", "observed_at"])
    op.create_table("runtime_terminal_session",
        sa.Column("terminal_session_id", sa.String(36), primary_key=True), sa.Column("runtime_instance_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False), sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_terminal_token_hash"))
    op.create_index("ix_terminal_instance_expiry", "runtime_terminal_session", ["runtime_instance_id", "expires_at"])
    op.create_table("runtime_artifact",
        sa.Column("runtime_artifact_id", sa.String(36), primary_key=True), sa.Column("runtime_instance_id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=True), sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("file_id", sa.String(36), nullable=False), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False), sa.Column("capture_started_at", sa.DateTime(), nullable=True),
        sa.Column("capture_ended_at", sa.DateTime(), nullable=True))
    op.create_index("ix_runtime_artifact_instance_type", "runtime_artifact", ["runtime_instance_id", "artifact_type"])
    op.create_table("checkpoint_result",
        sa.Column("checkpoint_result_id", sa.String(36), primary_key=True), sa.Column("runtime_instance_id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=True), sa.Column("checkpoint_id", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("score_awarded", sa.Integer(), nullable=False), sa.Column("max_score", sa.Integer(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False), sa.Column("message", sa.String(512), nullable=False),
        sa.Column("judged_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("runtime_instance_id", "checkpoint_id", "attempt", name="uq_checkpoint_result_attempt"))
    op.create_index("ix_checkpoint_result_student", "checkpoint_result", ["student_id", "judged_at"])


def downgrade() -> None:
    for table, indexes in [
        ("checkpoint_result", ["ix_checkpoint_result_student"]), ("runtime_artifact", ["ix_runtime_artifact_instance_type"]),
        ("runtime_terminal_session", ["ix_terminal_instance_expiry"]), ("runtime_resource_usage", ["ix_runtime_usage_instance_time"]),
        ("runtime_event", ["ix_runtime_event_instance_time"]), ("runtime_network", []),
        ("runtime_container", ["ix_runtime_container_instance"]), ("runtime_instance", ["ix_runtime_instance_group", "ix_runtime_instance_student_status"]),
        ("runtime_instance_group", ["ix_runtime_group_status"]), ("runtime_queue", ["ix_runtime_queue_state_priority"]),
        ("runtime_request", ["ix_runtime_request_status", "ix_runtime_request_subject"]),
        ("infra_image_validation", ["ix_image_validation_image_time"]), ("infra_image", ["ix_infra_image_enabled"]),
        ("infra_node_heartbeat", ["ix_heartbeat_node_time"]), ("infra_node", ["ix_infra_node_schedulable"]),
    ]:
        for index in indexes:
            op.drop_index(index, table_name=table)
        op.drop_table(table)
