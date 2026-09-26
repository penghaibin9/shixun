"""Persist authoritative course catalog lineage.

Revision ID: 20260926_0024
Revises: 20260925_0023
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "20260926_0024"
down_revision = "20260925_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "course",
        sa.Column(
            "catalog_key",
            sa.String(length=64),
            nullable=False,
            server_default="data_security_v1",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE course SET catalog_key='web_security_v1' "
            "WHERE course_id='course_web_security'"
        )
    )


def downgrade() -> None:
    op.drop_column("course", "catalog_key")
