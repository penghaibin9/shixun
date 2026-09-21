"""create lab designer tables

Revision ID: 20260921_0002
Revises: 20260921_0001
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0002"
down_revision = "20260921_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("lab_template",
        sa.Column("template_id", sa.String(36), primary_key=True), sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False), sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_lab_template_name"))
    op.create_table("lab_definition",
        sa.Column("lab_definition_id", sa.String(36), primary_key=True), sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(64), nullable=False), sa.Column("name", sa.String(160), nullable=False),
        sa.Column("category", sa.String(64), nullable=False), sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False), sa.UniqueConstraint("course_id", "code", name="uq_lab_definition_course_code"))
    op.create_index("ix_lab_definition_course", "lab_definition", ["course_id"])
    op.create_table("lab_version",
        sa.Column("lab_version_id", sa.String(36), primary_key=True),
        sa.Column("lab_definition_id", sa.String(36), sa.ForeignKey("lab_definition.lab_definition_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("spec_json", sa.JSON(), nullable=False), sa.Column("validation_errors_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False), sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("lab_definition_id", "version", name="uq_lab_version_number"))
    op.create_index("ix_lab_version_status", "lab_version", ["status"])
    op.create_table("lab_scene",
        sa.Column("scene_id", sa.String(36), primary_key=True),
        sa.Column("lab_version_id", sa.String(36), sa.ForeignKey("lab_version.lab_version_id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False))
    op.create_table("lab_scene_network",
        sa.Column("network_id", sa.String(36), primary_key=True),
        sa.Column("scene_id", sa.String(36), sa.ForeignKey("lab_scene.scene_id", ondelete="CASCADE"), nullable=False),
        sa.Column("network_key", sa.String(64), nullable=False), sa.Column("cidr_policy", sa.String(64), nullable=False),
        sa.Column("internet_access", sa.Boolean(), nullable=False), sa.Column("egress_allowlist_json", sa.JSON(), nullable=False),
        sa.Column("student_isolation", sa.Boolean(), nullable=False), sa.UniqueConstraint("scene_id", "network_key", name="uq_lab_network_key"))
    op.create_table("lab_scene_node",
        sa.Column("scene_node_id", sa.String(36), primary_key=True),
        sa.Column("scene_id", sa.String(36), sa.ForeignKey("lab_scene.scene_id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_key", sa.String(64), nullable=False), sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("role", sa.String(64), nullable=False), sa.Column("network_env", sa.String(16), nullable=False),
        sa.Column("network_keys_json", sa.JSON(), nullable=False), sa.Column("device_model", sa.String(128), nullable=False),
        sa.Column("cpu_limit", sa.Float(), nullable=False), sa.Column("memory_mb", sa.Integer(), nullable=False),
        sa.Column("ip_policy", sa.String(64), nullable=False), sa.Column("ports_json", sa.JSON(), nullable=False),
        sa.Column("startup_command", sa.String(512), nullable=False), sa.Column("mounts_json", sa.JSON(), nullable=False),
        sa.Column("position_x", sa.Integer(), nullable=False), sa.Column("position_y", sa.Integer(), nullable=False),
        sa.UniqueConstraint("scene_id", "node_key", name="uq_lab_scene_node_key"))
    op.create_table("lab_image_binding",
        sa.Column("image_binding_id", sa.String(36), primary_key=True),
        sa.Column("lab_version_id", sa.String(36), sa.ForeignKey("lab_version.lab_version_id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_key", sa.String(64), nullable=False), sa.Column("infra_image_id", sa.String(36), nullable=False),
        sa.Column("image_digest", sa.String(71), nullable=False), sa.UniqueConstraint("lab_version_id", "node_key", name="uq_lab_image_binding_node"))
    op.create_index("ix_lab_image_digest", "lab_image_binding", ["image_digest"])
    op.create_table("lab_dag_node",
        sa.Column("dag_node_id", sa.String(36), primary_key=True),
        sa.Column("lab_version_id", sa.String(36), sa.ForeignKey("lab_version.lab_version_id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_key", sa.String(64), nullable=False), sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False), sa.Column("order_no", sa.Integer(), nullable=False),
        sa.UniqueConstraint("lab_version_id", "node_key", name="uq_lab_dag_node_key"))
    op.create_table("lab_dag_edge",
        sa.Column("dag_edge_id", sa.String(36), primary_key=True),
        sa.Column("lab_version_id", sa.String(36), sa.ForeignKey("lab_version.lab_version_id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_node_key", sa.String(64), nullable=False), sa.Column("to_node_key", sa.String(64), nullable=False),
        sa.UniqueConstraint("lab_version_id", "from_node_key", "to_node_key", name="uq_lab_dag_edge"))
    op.create_table("lab_checkpoint",
        sa.Column("checkpoint_id", sa.String(36), primary_key=True), sa.Column("checkpoint_key", sa.String(64), nullable=False),
        sa.Column("lab_version_id", sa.String(36), sa.ForeignKey("lab_version.lab_version_id", ondelete="CASCADE"), nullable=False),
        sa.Column("dag_node_key", sa.String(64), nullable=False), sa.Column("name", sa.String(160), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False), sa.Column("judge_type", sa.String(32), nullable=False),
        sa.Column("judge_target", sa.String(512), nullable=False), sa.Column("judge_config_json", sa.JSON(), nullable=False),
        sa.Column("failure_message", sa.String(512), nullable=False), sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("order_no", sa.Integer(), nullable=False), sa.UniqueConstraint("lab_version_id", "checkpoint_key", name="uq_lab_checkpoint_key"))
    op.create_index("ix_lab_checkpoint_judge_type", "lab_checkpoint", ["judge_type"])
    op.create_table("lab_knowledge_point",
        sa.Column("knowledge_point_id", sa.String(36), primary_key=True), sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(160), nullable=False), sa.Column("explain_text", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_lab_knowledge_course", "lab_knowledge_point", ["course_id"])
    op.create_table("lab_question_knowledge_map",
        sa.Column("map_id", sa.String(36), primary_key=True),
        sa.Column("knowledge_point_id", sa.String(36), sa.ForeignKey("lab_knowledge_point.knowledge_point_id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.String(36), nullable=False), sa.UniqueConstraint("knowledge_point_id", "question_id", name="uq_lab_knowledge_question"))
    op.create_index("ix_lab_question_ref", "lab_question_knowledge_map", ["question_id"])
    op.create_table("lab_explain_diagram",
        sa.Column("diagram_id", sa.String(36), primary_key=True),
        sa.Column("knowledge_point_id", sa.String(36), sa.ForeignKey("lab_knowledge_point.knowledge_point_id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", sa.String(36), nullable=False), sa.Column("title", sa.String(160), nullable=False), sa.Column("order_no", sa.Integer(), nullable=False))
    op.create_index("ix_lab_diagram_file", "lab_explain_diagram", ["file_id"])
    op.create_table("lab_release",
        sa.Column("lab_release_id", sa.String(36), primary_key=True),
        sa.Column("lab_version_id", sa.String(36), sa.ForeignKey("lab_version.lab_version_id"), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False), sa.Column("class_id", sa.String(36), nullable=False),
        sa.Column("lesson_id", sa.String(36), nullable=True), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True))
    op.create_index("ix_lab_release_class_status", "lab_release", ["class_id", "status"])
    op.create_table("lab_publish_config",
        sa.Column("publish_config_id", sa.String(36), primary_key=True),
        sa.Column("lab_release_id", sa.String(36), sa.ForeignKey("lab_release.lab_release_id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("opens_at", sa.DateTime(), nullable=False), sa.Column("closes_at", sa.DateTime(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False), sa.Column("timeout_minutes", sa.Integer(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False), sa.Column("teacher_preview_required", sa.Boolean(), nullable=False),
        sa.Column("preflight_json", sa.JSON(), nullable=False), sa.Column("preview_request_id", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_table("lab_publish_config")
    op.drop_index("ix_lab_release_class_status", table_name="lab_release")
    op.drop_table("lab_release")
    op.drop_index("ix_lab_diagram_file", table_name="lab_explain_diagram")
    op.drop_table("lab_explain_diagram")
    op.drop_index("ix_lab_question_ref", table_name="lab_question_knowledge_map")
    op.drop_table("lab_question_knowledge_map")
    op.drop_index("ix_lab_knowledge_course", table_name="lab_knowledge_point")
    op.drop_table("lab_knowledge_point")
    op.drop_index("ix_lab_checkpoint_judge_type", table_name="lab_checkpoint")
    op.drop_table("lab_checkpoint")
    op.drop_table("lab_dag_edge")
    op.drop_table("lab_dag_node")
    op.drop_index("ix_lab_image_digest", table_name="lab_image_binding")
    op.drop_table("lab_image_binding")
    op.drop_table("lab_scene_node")
    op.drop_table("lab_scene_network")
    op.drop_table("lab_scene")
    op.drop_index("ix_lab_version_status", table_name="lab_version")
    op.drop_table("lab_version")
    op.drop_index("ix_lab_definition_course", table_name="lab_definition")
    op.drop_table("lab_definition")
    op.drop_table("lab_template")
