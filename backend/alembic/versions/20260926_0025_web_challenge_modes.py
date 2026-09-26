"""Align Web challenge validation modes with four original runtime specs.

Revision ID: 20260926_0025
Revises: 20260926_0024
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "20260926_0025"
down_revision = "20260926_0024"
branch_labels = None
depends_on = None

ORIGINAL_CHECKPOINT_ONLY = (
    "challenge_web_01",
    "challenge_web_08",
    "challenge_web_09",
    "challenge_web_10",
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE challenge_definition "
            "SET validation_mode='FLAG_AND_CHECKPOINT' "
            "WHERE course_id='course_web_security'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE challenge_definition "
            "SET validation_mode='CHECKPOINT_ONLY' "
            "WHERE course_id='course_web_security' "
            "AND challenge_id IN ('challenge_web_01','challenge_web_08','challenge_web_09','challenge_web_10')"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE challenge_definition "
            "SET validation_mode='FLAG_AND_CHECKPOINT' "
            "WHERE course_id='course_web_security'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE challenge_definition "
            "SET validation_mode='CHECKPOINT_ONLY' "
            "WHERE course_id='course_web_security' "
            "AND challenge_id IN ('challenge_web_01','challenge_web_02','challenge_web_03','challenge_web_04','challenge_web_05','challenge_web_06')"
        )
    )
