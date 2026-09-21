"""add question import rows and independent review queue

Revision ID: 20260921_0011
Revises: 20260921_0010
"""
from alembic import context, op
import sqlalchemy as sa


revision = "20260921_0011"
down_revision = "20260921_0010"
branch_labels = None
depends_on = None


def _assert_unique_legacy_data() -> None:
    if context.is_offline_mode():
        return
    connection = op.get_bind()
    duplicate_bank = connection.execute(
        sa.text("SELECT course_id FROM question_bank GROUP BY course_id HAVING COUNT(*) > 1 LIMIT 1")
    ).first()
    if duplicate_bank:
        raise RuntimeError("迁移中止：question_bank 存在同课程重复题库，请先人工合并后再升级")
    duplicate_option = connection.execute(
        sa.text(
            "SELECT question_id, option_key FROM question_option "
            "GROUP BY question_id, option_key HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate_option:
        raise RuntimeError("迁移中止：question_option 存在同题重复选项键，请先人工清理后再升级")


def upgrade() -> None:
    _assert_unique_legacy_data()
    op.create_unique_constraint("uq_question_bank_course", "question_bank", ["course_id"])

    op.create_table(
        "question_import_job",
        sa.Column("import_job_id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column(
            "question_bank_id",
            sa.String(36),
            sa.ForeignKey("question_bank.question_bank_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("course_id", "idempotency_key", name="uq_question_import_course_idempotency"),
    )
    op.create_index(
        "ix_question_import_job_question_bank_id",
        "question_import_job",
        ["question_bank_id"],
    )
    op.create_index(
        "ix_question_import_course_created",
        "question_import_job",
        ["course_id", "created_at"],
    )

    op.add_column("question", sa.Column("import_job_id", sa.String(36), nullable=True))
    op.add_column("question", sa.Column("source_row_number", sa.Integer(), nullable=True))
    op.add_column("question", sa.Column("submitted_at", sa.DateTime(), nullable=True))
    op.create_foreign_key(
        "fk_question_import_job",
        "question",
        "question_import_job",
        ["import_job_id"],
        ["import_job_id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_question_import_job_id", "question", ["import_job_id"])
    op.create_unique_constraint(
        "uq_question_import_source_row",
        "question",
        ["import_job_id", "source_row_number"],
    )
    op.create_index(
        "ix_question_bank_status_created",
        "question",
        ["question_bank_id", "status", "created_at"],
    )

    op.create_table(
        "question_import_row",
        sa.Column("import_row_id", sa.String(36), primary_key=True),
        sa.Column(
            "import_job_id",
            sa.String(36),
            sa.ForeignKey("question_import_job.import_job_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("raw_data_json", sa.JSON(), nullable=False),
        sa.Column("normalized_data_json", sa.JSON(), nullable=True),
        sa.Column("errors_json", sa.JSON(), nullable=False),
        sa.Column(
            "question_id",
            sa.String(36),
            sa.ForeignKey("question.question_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("import_job_id", "row_number", name="uq_question_import_job_row"),
    )
    op.create_index(
        "ix_question_import_row_status",
        "question_import_row",
        ["import_job_id", "status", "row_number"],
    )
    op.create_index("ix_question_import_row_question_id", "question_import_row", ["question_id"])

    op.create_table(
        "question_review",
        sa.Column("question_review_id", sa.String(36), primary_key=True),
        sa.Column(
            "question_id",
            sa.String(36),
            sa.ForeignKey("question.question_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_question_review_question_reviewed",
        "question_review",
        ["question_id", "reviewed_at"],
    )

    op.create_unique_constraint(
        "uq_question_option_key",
        "question_option",
        ["question_id", "option_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_question_option_key", "question_option", type_="unique")
    op.drop_table("question_review")
    op.drop_table("question_import_row")

    op.drop_index("ix_question_bank_status_created", table_name="question")
    op.drop_constraint("uq_question_import_source_row", "question", type_="unique")
    op.drop_constraint("fk_question_import_job", "question", type_="foreignkey")
    op.drop_index("ix_question_import_job_id", table_name="question")
    op.drop_column("question", "submitted_at")
    op.drop_column("question", "source_row_number")
    op.drop_column("question", "import_job_id")

    op.drop_table("question_import_job")
    op.drop_constraint("uq_question_bank_course", "question_bank", type_="unique")
