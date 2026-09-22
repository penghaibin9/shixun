"""add fail-closed grade source provenance

Revision ID: 20260922_0019
Revises: 20260922_0018
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0019"
down_revision = "20260922_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The server default deliberately quarantines records written by an older
    # application during a rolling deployment. They remain traceable, but F's
    # gradebook query will not silently treat them as verified facts.
    op.add_column(
        "grade_event",
        sa.Column(
            "source_verification_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'QUARANTINED_LEGACY'"),
        ),
    )
    op.add_column("grade_event", sa.Column("source_proof_issuer", sa.String(length=48), nullable=True))
    op.add_column("grade_event", sa.Column("source_proof_digest", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_grade_event_verification_scope",
        "grade_event",
        ["source_verification_status", "course_id", "class_id"],
    )
    op.create_table(
        "grade_score_proof",
        sa.Column("source_proof_event_id", sa.String(length=36), nullable=False),
        sa.Column("score_event_id", sa.String(length=36), nullable=False),
        sa.Column("score_event_type", sa.String(length=64), nullable=False),
        sa.Column("score_aggregate_id", sa.String(length=36), nullable=False),
        sa.Column("source_fact_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("class_id", sa.String(length=36), nullable=False),
        sa.Column("lesson_id", sa.String(length=36), nullable=True),
        sa.Column("student_id", sa.String(length=36), nullable=False),
        sa.Column("raw_score", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("max_score", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("contract", sa.String(length=64), nullable=False),
        sa.Column("issuer", sa.String(length=48), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("frozen_question_count", sa.Integer(), nullable=False),
        sa.Column("frozen_question_sha256", sa.String(length=64), nullable=False),
        sa.Column("answer_evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("scoring_evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("score_payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("source_proof_event_id"),
        sa.UniqueConstraint("score_event_id", name="uq_grade_score_proof_score_event"),
    )
    op.create_index("ix_grade_score_proof_scope", "grade_score_proof", ["course_id", "class_id", "student_id"])


def downgrade() -> None:
    op.drop_index("ix_grade_score_proof_scope", table_name="grade_score_proof")
    op.drop_table("grade_score_proof")
    op.drop_index("ix_grade_event_verification_scope", table_name="grade_event")
    op.drop_column("grade_event", "source_proof_digest")
    op.drop_column("grade_event", "source_proof_issuer")
    op.drop_column("grade_event", "source_verification_status")
