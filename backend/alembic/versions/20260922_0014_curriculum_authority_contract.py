"""remove duplicated lesson facts from the resource extension

Revision ID: 20260922_0014
Revises: 20260922_0013
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0014"
down_revision = "20260922_0013"
branch_labels = None
depends_on = None


def _assert_extension_matches_authority(bind) -> None:
    conflict = bind.execute(
        sa.text(
            """
            SELECT lr.lesson_resource_id, lr.course_id, lr.lesson_id
            FROM lesson_resource lr
            LEFT JOIN course_lesson cl
              ON cl.course_id = lr.course_id AND cl.lesson_id = lr.lesson_id
            LEFT JOIN course_chapter cc
              ON cc.course_id = cl.course_id AND cc.chapter_id = cl.chapter_id
            WHERE cl.lesson_id IS NULL
               OR lr.lesson_kind <> cl.lesson_type
               OR lr.lesson_code <> cl.lesson_code
               OR lr.title <> cl.title
               OR (cl.lesson_type = 'THEORY' AND (lr.chapter_no IS NULL OR lr.chapter_no <> cc.sequence))
               OR (cl.lesson_type = 'LAB' AND lr.chapter_no IS NOT NULL)
            LIMIT 1
            """
        )
    ).first()
    if conflict:
        raise RuntimeError(f"课程资源扩展与 A 权威课时事实不一致，拒绝删除重复字段: {tuple(conflict)}")


def upgrade() -> None:
    bind = op.get_bind()
    _assert_extension_matches_authority(bind)
    op.drop_index("ix_lesson_resource_kind", table_name="lesson_resource")
    op.drop_column("lesson_resource", "title")
    op.drop_column("lesson_resource", "lesson_code")
    op.drop_column("lesson_resource", "chapter_no")
    op.drop_column("lesson_resource", "lesson_kind")


def downgrade() -> None:
    op.add_column("lesson_resource", sa.Column("lesson_kind", sa.String(16), nullable=True))
    op.add_column("lesson_resource", sa.Column("chapter_no", sa.Integer(), nullable=True))
    op.add_column("lesson_resource", sa.Column("lesson_code", sa.String(16), nullable=True))
    op.add_column("lesson_resource", sa.Column("title", sa.String(255), nullable=True))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE lesson_resource lr
            JOIN course_lesson cl
              ON cl.course_id = lr.course_id AND cl.lesson_id = lr.lesson_id
            JOIN course_chapter cc
              ON cc.course_id = cl.course_id AND cc.chapter_id = cl.chapter_id
            SET lr.lesson_kind = cl.lesson_type,
                lr.chapter_no = CASE WHEN cl.lesson_type = 'THEORY' THEN cc.sequence ELSE NULL END,
                lr.lesson_code = cl.lesson_code,
                lr.title = cl.title
            """
        )
    )
    op.alter_column("lesson_resource", "lesson_kind", existing_type=sa.String(16), nullable=False)
    op.alter_column("lesson_resource", "lesson_code", existing_type=sa.String(16), nullable=False)
    op.alter_column("lesson_resource", "title", existing_type=sa.String(255), nullable=False)
    op.create_index(
        "ix_lesson_resource_kind",
        "lesson_resource",
        ["course_id", "lesson_kind", "lesson_code"],
    )
