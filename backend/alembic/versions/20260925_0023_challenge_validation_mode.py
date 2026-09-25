"""Add challenge validation modes.

Revision ID: 20260925_0023
Revises: 20260925_0022
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "20260925_0023"
down_revision = "20260925_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "challenge_definition",
        sa.Column(
            "validation_mode",
            sa.String(length=32),
            nullable=False,
            server_default="FLAG_AND_CHECKPOINT",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE challenge_definition "
            "SET validation_mode='CHECKPOINT_ONLY' "
            "WHERE course_id='course_web_security' "
            "AND challenge_id IN ("
            "'challenge_web_01','challenge_web_02','challenge_web_03',"
            "'challenge_web_04','challenge_web_05','challenge_web_06')"
        )
    )


def downgrade() -> None:
    op.drop_column("challenge_definition", "validation_mode")
