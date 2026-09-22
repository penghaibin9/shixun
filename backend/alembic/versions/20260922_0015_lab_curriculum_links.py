"""freeze lab definitions against the authoritative curriculum

Revision ID: 20260922_0015
Revises: 20260922_0014
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0015"
down_revision = "20260922_0014"
branch_labels = None
depends_on = None


def _fail_if_rows(bind, sql: str, message: str) -> None:
    row = bind.execute(sa.text(sql)).first()
    if row:
        raise RuntimeError(f"{message}: {tuple(row)}")


def upgrade() -> None:
    bind = op.get_bind()
    _fail_if_rows(
        bind,
        """
        SELECT ld.lab_definition_id, ld.course_id
        FROM lab_definition ld
        LEFT JOIN course c ON c.course_id = ld.course_id
        WHERE c.course_id IS NULL
        LIMIT 1
        """,
        "实验定义引用了不存在的课程，拒绝冻结契约",
    )
    _fail_if_rows(
        bind,
        """
        SELECT kp.knowledge_point_id, kp.course_id
        FROM lab_knowledge_point kp
        LEFT JOIN course c ON c.course_id = kp.course_id
        WHERE c.course_id IS NULL
        LIMIT 1
        """,
        "实验知识点引用了不存在的课程，拒绝冻结契约",
    )
    _fail_if_rows(
        bind,
        """
        SELECT lr.lab_release_id, lr.course_id, lr.class_id
        FROM lab_release lr
        LEFT JOIN class_course cc
          ON cc.class_id = lr.class_id AND cc.course_id = lr.course_id
        WHERE cc.class_course_id IS NULL
        LIMIT 1
        """,
        "实验发布引用了未开课的班级与课程组合，拒绝冻结契约",
    )
    _fail_if_rows(
        bind,
        """
        SELECT lr.lab_release_id, lr.lab_version_id, lr.course_id, ld.course_id
        FROM lab_release lr
        JOIN lab_version lv ON lv.lab_version_id = lr.lab_version_id
        JOIN lab_definition ld ON ld.lab_definition_id = lv.lab_definition_id
        WHERE lr.course_id <> ld.course_id
        LIMIT 1
        """,
        "实验发布记录与实验版本所属课程不一致，拒绝冻结契约",
    )
    _fail_if_rows(
        bind,
        """
        SELECT lr.lab_release_id, lr.course_id, lr.lesson_id
        FROM lab_release lr
        WHERE lr.lesson_id IS NULL
        LIMIT 1
        """,
        "实验发布记录缺少正式实验课时，拒绝冻结契约",
    )
    _fail_if_rows(
        bind,
        """
        SELECT lr.lab_release_id, lr.course_id, lr.lesson_id
        FROM lab_release lr
        LEFT JOIN course_lesson cl
          ON cl.course_id = lr.course_id AND cl.lesson_id = lr.lesson_id
        WHERE lr.lesson_id IS NOT NULL AND cl.lesson_id IS NULL
        LIMIT 1
        """,
        "实验发布引用了不存在或跨课程的课时，拒绝冻结契约",
    )
    _fail_if_rows(
        bind,
        """
        SELECT lr.lab_release_id, lr.lesson_id, ld.lab_definition_id,
               lesson.linked_lab_definition_id
        FROM lab_release lr
        JOIN lab_version lv ON lv.lab_version_id = lr.lab_version_id
        JOIN lab_definition ld ON ld.lab_definition_id = lv.lab_definition_id
        LEFT JOIN lesson_resource lesson
          ON lesson.course_id = lr.course_id
         AND lesson.lesson_id = lr.lesson_id
         AND lesson.linked_lab_definition_id = ld.lab_definition_id
        WHERE lesson.lesson_resource_id IS NULL
        LIMIT 1
        """,
        "实验发布课时未关联该实验定义，拒绝冻结契约",
    )
    _fail_if_rows(
        bind,
        """
        SELECT lr.lesson_resource_id, lr.course_id, lr.linked_lab_definition_id
        FROM lesson_resource lr
        LEFT JOIN lab_definition ld
          ON ld.course_id = lr.course_id
         AND ld.lab_definition_id = lr.linked_lab_definition_id
        WHERE lr.linked_lab_definition_id IS NOT NULL
          AND ld.lab_definition_id IS NULL
        LIMIT 1
        """,
        "课程资源引用了不存在或跨课程的实验定义，拒绝冻结契约",
    )
    _fail_if_rows(
        bind,
        """
        SELECT m.map_id, m.question_id
        FROM lab_question_knowledge_map m
        LEFT JOIN question q ON q.question_id = m.question_id
        WHERE q.question_id IS NULL
        LIMIT 1
        """,
        "实验知识点引用了不存在的题目，拒绝冻结契约",
    )
    _fail_if_rows(
        bind,
        """
        SELECT d.diagram_id, d.file_id
        FROM lab_explain_diagram d
        LEFT JOIN file_object f ON f.file_id = d.file_id
        WHERE f.file_id IS NULL
        LIMIT 1
        """,
        "实验讲解图引用了不存在的文件，拒绝冻结契约",
    )

    op.alter_column(
        "lab_release",
        "lesson_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )

    op.create_unique_constraint(
        "uq_lab_definition_course_scope",
        "lab_definition",
        ["course_id", "lab_definition_id"],
    )
    op.create_foreign_key(
        "fk_lab_definition_course",
        "lab_definition",
        "course",
        ["course_id"],
        ["course_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_lab_knowledge_course",
        "lab_knowledge_point",
        "course",
        ["course_id"],
        ["course_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_lab_release_course",
        "lab_release",
        "course",
        ["course_id"],
        ["course_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_lab_release_class_course",
        "lab_release",
        "class_course",
        ["class_id", "course_id"],
        ["class_id", "course_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_lab_release_course_lesson",
        "lab_release",
        "course_lesson",
        ["course_id", "lesson_id"],
        ["course_id", "lesson_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_lesson_resource_lab_definition",
        "lesson_resource",
        ["course_id", "linked_lab_definition_id"],
    )
    op.create_foreign_key(
        "fk_lesson_resource_lab_definition",
        "lesson_resource",
        "lab_definition",
        ["course_id", "linked_lab_definition_id"],
        ["course_id", "lab_definition_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_lab_question_knowledge_question",
        "lab_question_knowledge_map",
        "question",
        ["question_id"],
        ["question_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_lab_explain_diagram_file",
        "lab_explain_diagram",
        "file_object",
        ["file_id"],
        ["file_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_lab_explain_diagram_file", "lab_explain_diagram", type_="foreignkey")
    op.drop_constraint("fk_lab_question_knowledge_question", "lab_question_knowledge_map", type_="foreignkey")
    op.drop_constraint("fk_lesson_resource_lab_definition", "lesson_resource", type_="foreignkey")
    op.drop_index("ix_lesson_resource_lab_definition", table_name="lesson_resource")
    op.drop_constraint("fk_lab_release_course_lesson", "lab_release", type_="foreignkey")
    op.drop_constraint("fk_lab_release_class_course", "lab_release", type_="foreignkey")
    op.drop_constraint("fk_lab_release_course", "lab_release", type_="foreignkey")
    op.drop_constraint("fk_lab_knowledge_course", "lab_knowledge_point", type_="foreignkey")
    op.drop_constraint("fk_lab_definition_course", "lab_definition", type_="foreignkey")
    op.drop_constraint("uq_lab_definition_course_scope", "lab_definition", type_="unique")
    op.alter_column(
        "lab_release",
        "lesson_id",
        existing_type=sa.String(length=36),
        nullable=True,
    )
