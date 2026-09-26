"""Bind challenge completion to frozen runtime evidence.

Revision ID: 20260925_0022
Revises: 20260925_0021
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "20260925_0022"
down_revision = "20260925_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("challenge_definition", sa.Column("lab_version_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_challenge_lab_version",
        "challenge_definition",
        "lab_version",
        ["lab_version_id"],
        ["lab_version_id"],
        ondelete="RESTRICT",
    )
    op.add_column("challenge_attempt", sa.Column("runtime_instance_id", sa.String(length=36), nullable=True))
    op.add_column("challenge_attempt", sa.Column("checkpoint_result_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_challenge_attempt_runtime_instance",
        "challenge_attempt",
        "runtime_instance",
        ["runtime_instance_id"],
        ["runtime_instance_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_challenge_attempt_checkpoint_result",
        "challenge_attempt",
        "checkpoint_result",
        ["checkpoint_result_id"],
        ["checkpoint_result_id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_challenge_attempt_runtime", "challenge_attempt", ["runtime_instance_id", "checkpoint_result_id"])


def downgrade() -> None:
    op.drop_index("ix_challenge_attempt_runtime", table_name="challenge_attempt")
    op.drop_constraint("fk_challenge_attempt_checkpoint_result", "challenge_attempt", type_="foreignkey")
    op.drop_constraint("fk_challenge_attempt_runtime_instance", "challenge_attempt", type_="foreignkey")
    op.drop_column("challenge_attempt", "checkpoint_result_id")
    op.drop_column("challenge_attempt", "runtime_instance_id")
    op.drop_constraint("fk_challenge_lab_version", "challenge_definition", type_="foreignkey")
    op.drop_column("challenge_definition", "lab_version_id")
