"""freeze server-scored teaching proof facts

Revision ID: 20260922_0020
Revises: 20260922_0019
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0020"
down_revision = "20260922_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing task snapshots only held a short client-facing version.  New
    # tasks retain the full server-derived SHA256 content version instead.
    op.alter_column(
        "assignment_question_ref",
        "question_version",
        existing_type=sa.String(length=40),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "quiz_question_ref",
        "question_version",
        existing_type=sa.String(length=40),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_table(
        "teaching_score_proof",
        sa.Column("proof_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_fact_id", sa.String(length=36), nullable=False),
        sa.Column("score_event_id", sa.String(length=36), nullable=False),
        sa.Column("score_proof_event_id", sa.String(length=36), nullable=False),
        sa.Column("score_aggregate_id", sa.String(length=36), nullable=False),
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
        sa.Column("frozen_question_evidence_json", sa.JSON(), nullable=False),
        sa.Column("answer_evidence_json", sa.JSON(), nullable=False),
        sa.Column("scoring_evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("proof_id"),
        sa.UniqueConstraint("source_fact_id", name="uq_teaching_score_proof_source_fact"),
        sa.UniqueConstraint("score_event_id", name="uq_teaching_score_proof_score_event"),
        sa.UniqueConstraint("score_proof_event_id", name="uq_teaching_score_proof_event"),
    )
    op.create_index("ix_teaching_score_proof_course_id", "teaching_score_proof", ["course_id"])
    op.create_index("ix_teaching_score_proof_class_id", "teaching_score_proof", ["class_id"])
    op.create_index("ix_teaching_score_proof_student_id", "teaching_score_proof", ["student_id"])
    op.create_index("ix_teaching_score_proof_scope", "teaching_score_proof", ["course_id", "class_id", "student_id"])


def downgrade() -> None:
    op.drop_index("ix_teaching_score_proof_scope", table_name="teaching_score_proof")
    op.drop_index("ix_teaching_score_proof_student_id", table_name="teaching_score_proof")
    op.drop_index("ix_teaching_score_proof_class_id", table_name="teaching_score_proof")
    op.drop_index("ix_teaching_score_proof_course_id", table_name="teaching_score_proof")
    op.drop_table("teaching_score_proof")
    op.alter_column(
        "quiz_question_ref",
        "question_version",
        existing_type=sa.String(length=64),
        type_=sa.String(length=40),
        existing_nullable=False,
    )
    op.alter_column(
        "assignment_question_ref",
        "question_version",
        existing_type=sa.String(length=64),
        type_=sa.String(length=40),
        existing_nullable=False,
    )
