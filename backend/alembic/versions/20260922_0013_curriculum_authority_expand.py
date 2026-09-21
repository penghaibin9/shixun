"""move course and lesson authority to teaching core

Revision ID: 20260922_0013
Revises: 20260921_0012
"""

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "20260922_0013"
down_revision = "20260921_0012"
branch_labels = None
depends_on = None


CHAPTER_TITLES = {
    1: "数据安全基础",
    2: "数据资产分类分级",
    3: "数据加密与完整性保护",
    4: "数据脱敏与访问管控",
    5: "数据溯源与隐私保护",
    6: "数据灾备与安全销毁",
    7: "数据安全治理实践",
    8: "实验课程",
}


def _fail_if_rows(bind, sql: str, message: str) -> None:
    row = bind.execute(sa.text(sql)).first()
    if row:
        raise RuntimeError(f"{message}: {tuple(row)}")


def _drop_single_column_fk(bind, table_name: str, column_name: str, referred_table: str) -> None:
    """Replace a legacy single-column FK with the scoped composite FK."""
    for constraint in sa.inspect(bind).get_foreign_keys(table_name):
        if constraint.get("constrained_columns") == [column_name] and constraint.get("referred_table") == referred_table:
            op.drop_constraint(constraint["name"], table_name, type_="foreignkey")
            return


def _preflight(bind) -> None:
    _fail_if_rows(
        bind,
        """
        SELECT lesson_id, COUNT(DISTINCT course_id)
        FROM lesson_resource
        GROUP BY lesson_id
        HAVING COUNT(DISTINCT course_id) > 1
        LIMIT 1
        """,
        "同一课时标识被多个课程复用，拒绝迁移",
    )
    _fail_if_rows(
        bind,
        """
        SELECT course_id, lesson_code, COUNT(*)
        FROM lesson_resource
        GROUP BY course_id, lesson_code
        HAVING COUNT(*) > 1
        LIMIT 1
        """,
        "课程内存在重复课时编号，拒绝迁移",
    )
    _fail_if_rows(
        bind,
        """
        SELECT lr.lesson_id, lr.course_id, cl.course_id, lr.title, cl.title
        FROM lesson_resource lr
        JOIN course_lesson cl ON cl.lesson_id = lr.lesson_id
        WHERE cl.course_id <> lr.course_id
           OR cl.title <> lr.title
           OR cl.lesson_type <> lr.lesson_kind
        LIMIT 1
        """,
        "A/B 已有课时事实冲突，拒绝静默覆盖",
    )
    _fail_if_rows(
        bind,
        """
        SELECT r.resource_id, r.course_id, r.lesson_id
        FROM resource r
        LEFT JOIN lesson_resource lr
          ON lr.course_id = r.course_id AND lr.lesson_id = r.lesson_id
        LEFT JOIN course_lesson cl
          ON cl.course_id = r.course_id AND cl.lesson_id = r.lesson_id
        WHERE r.lesson_id IS NOT NULL AND lr.lesson_id IS NULL AND cl.lesson_id IS NULL
        LIMIT 1
        """,
        "资源引用了不存在或跨课程的课时，拒绝迁移",
    )
    _fail_if_rows(
        bind,
        """
        SELECT qlm.question_lesson_map_id, qb.course_id, qlm.lesson_id
        FROM question_lesson_map qlm
        JOIN question q ON q.question_id = qlm.question_id
        JOIN question_bank qb ON qb.question_bank_id = q.question_bank_id
        LEFT JOIN lesson_resource lr
          ON lr.course_id = qb.course_id AND lr.lesson_id = qlm.lesson_id
        LEFT JOIN course_lesson cl
          ON cl.course_id = qb.course_id AND cl.lesson_id = qlm.lesson_id
        WHERE lr.lesson_id IS NULL AND cl.lesson_id IS NULL
        LIMIT 1
        """,
        "题目映射引用了不存在或跨课程的课时，拒绝迁移",
    )
    _fail_if_rows(
        bind,
        """
        SELECT qij.import_job_id, qij.course_id, qb.course_id
        FROM question_import_job qij
        JOIN question_bank qb ON qb.question_bank_id = qij.question_bank_id
        WHERE qij.course_id <> qb.course_id
        LIMIT 1
        """,
        "题库导入任务与题库课程不一致，拒绝迁移",
    )


def _ensure_courses(bind) -> None:
    course_ids = bind.execute(
        sa.text(
            """
            SELECT DISTINCT course_id FROM lesson_resource
            UNION SELECT DISTINCT course_id FROM resource
            UNION SELECT DISTINCT course_id FROM resource_quality_check
            UNION SELECT DISTINCT course_id FROM resource_delivery_manifest
            UNION SELECT DISTINCT course_id FROM question_bank
            UNION SELECT DISTINCT course_id FROM question_import_job
            """
        )
    ).scalars().all()
    for course_id in course_ids:
        if bind.execute(sa.text("SELECT 1 FROM course WHERE course_id=:course_id"), {"course_id": course_id}).first():
            continue
        name = "数据安全技术基础" if course_id == "course_data_security" else f"迁移课程 {course_id}"
        bind.execute(
            sa.text(
                """
                INSERT INTO course
                    (course_id, name, term, owner_teacher_id, major, description, status, created_at)
                VALUES
                    (:course_id, :name, :term, :owner, :major, :description, :status, :created_at)
                """
            ),
            {
                "course_id": course_id,
                "name": name,
                "term": "2026 秋季",
                "owner": "system_curriculum_migration",
                "major": "网络空间安全",
                "description": "由课程资源历史目录迁入教学核心的权威课程事实。",
                "status": "ACTIVE",
                "created_at": datetime.utcnow(),
            },
        )


def _chapter_id(course_id: str, sequence: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"yueke:{course_id}:chapter:{sequence}"))


def _backfill_lessons(bind) -> None:
    rows = bind.execute(
        sa.text(
            """
            SELECT course_id, lesson_id, lesson_kind, chapter_no, lesson_code, title
            FROM lesson_resource
            ORDER BY course_id, lesson_kind, chapter_no, lesson_code, lesson_id
            """
        )
    ).mappings().all()
    chapter_cache: dict[tuple[str, int], str] = {}
    for row in rows:
        sequence = int(row["chapter_no"] or 8)
        key = (row["course_id"], sequence)
        if key not in chapter_cache:
            existing = bind.execute(
                sa.text("SELECT chapter_id FROM course_chapter WHERE course_id=:course_id AND sequence=:sequence"),
                {"course_id": row["course_id"], "sequence": sequence},
            ).scalar_one_or_none()
            chapter_id = existing or _chapter_id(row["course_id"], sequence)
            if not existing:
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO course_chapter (chapter_id, course_id, title, sequence)
                        VALUES (:chapter_id, :course_id, :title, :sequence)
                        """
                    ),
                    {
                        "chapter_id": chapter_id,
                        "course_id": row["course_id"],
                        "title": CHAPTER_TITLES.get(sequence, f"第 {sequence} 章"),
                        "sequence": sequence,
                    },
                )
            chapter_cache[key] = chapter_id

        existing = bind.execute(
            sa.text("SELECT lesson_id FROM course_lesson WHERE lesson_id=:lesson_id"),
            {"lesson_id": row["lesson_id"]},
        ).scalar_one_or_none()
        if existing:
            bind.execute(
                sa.text("UPDATE course_lesson SET lesson_code=:lesson_code WHERE lesson_id=:lesson_id"),
                {"lesson_code": row["lesson_code"], "lesson_id": row["lesson_id"]},
            )
            continue
        code = str(row["lesson_code"])
        if row["lesson_kind"] == "THEORY" and "." in code:
            lesson_sequence = int(code.split(".", 1)[1])
        else:
            digits = "".join(character for character in code if character.isdigit())
            lesson_sequence = int(digits or 1)
        bind.execute(
            sa.text(
                """
                INSERT INTO course_lesson
                    (lesson_id, course_id, chapter_id, lesson_code, title, sequence, lesson_type)
                VALUES
                    (:lesson_id, :course_id, :chapter_id, :lesson_code, :title, :sequence, :lesson_type)
                """
            ),
            {
                "lesson_id": row["lesson_id"],
                "course_id": row["course_id"],
                "chapter_id": chapter_cache[key],
                "lesson_code": row["lesson_code"],
                "title": row["title"],
                "sequence": lesson_sequence,
                "lesson_type": row["lesson_kind"],
            },
        )

    courses = bind.execute(sa.text("SELECT DISTINCT course_id FROM course_lesson ORDER BY course_id")).scalars().all()
    for course_id in courses:
        used = set(
            bind.execute(
                sa.text("SELECT lesson_code FROM course_lesson WHERE course_id=:course_id AND lesson_code IS NOT NULL"),
                {"course_id": course_id},
            ).scalars()
        )
        missing = bind.execute(
            sa.text(
                """
                SELECT lesson_id FROM course_lesson
                WHERE course_id=:course_id AND lesson_code IS NULL
                ORDER BY chapter_id, sequence, lesson_id
                """
            ),
            {"course_id": course_id},
        ).scalars().all()
        next_number = 1
        for lesson_id in missing:
            while f"L{next_number:03d}" in used:
                next_number += 1
            code = f"L{next_number:03d}"
            bind.execute(
                sa.text("UPDATE course_lesson SET lesson_code=:code WHERE lesson_id=:lesson_id"),
                {"code": code, "lesson_id": lesson_id},
            )
            used.add(code)
            next_number += 1


def upgrade() -> None:
    bind = op.get_bind()
    _preflight(bind)
    op.add_column("course_lesson", sa.Column("lesson_code", sa.String(16), nullable=True))
    _ensure_courses(bind)
    _backfill_lessons(bind)

    _fail_if_rows(
        bind,
        """
        SELECT course_id, lesson_code, COUNT(*)
        FROM course_lesson
        GROUP BY course_id, lesson_code
        HAVING lesson_code IS NULL OR COUNT(*) > 1
        LIMIT 1
        """,
        "A 权威课时编号不完整或重复，拒绝建立约束",
    )

    op.alter_column("course_lesson", "lesson_code", existing_type=sa.String(16), nullable=False)
    op.create_unique_constraint("uq_course_chapter_scope", "course_chapter", ["course_id", "chapter_id"])
    op.create_unique_constraint("uq_course_lesson_scope", "course_lesson", ["course_id", "lesson_id"])
    op.create_unique_constraint("uq_course_lesson_code", "course_lesson", ["course_id", "lesson_code"])
    _drop_single_column_fk(bind, "course_lesson", "chapter_id", "course_chapter")
    op.create_foreign_key(
        "fk_course_lesson_chapter_scope",
        "course_lesson",
        "course_chapter",
        ["course_id", "chapter_id"],
        ["course_id", "chapter_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key("fk_resource_course", "resource", "course", ["course_id"], ["course_id"], ondelete="RESTRICT")
    op.create_foreign_key(
        "fk_resource_course_lesson",
        "resource",
        "course_lesson",
        ["course_id", "lesson_id"],
        ["course_id", "lesson_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_lesson_resource_course_lesson",
        "lesson_resource",
        "course_lesson",
        ["course_id", "lesson_id"],
        ["course_id", "lesson_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key("fk_resource_quality_course", "resource_quality_check", "course", ["course_id"], ["course_id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_resource_delivery_course", "resource_delivery_manifest", "course", ["course_id"], ["course_id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_question_bank_scope", "question_bank", ["course_id", "question_bank_id"])
    op.create_foreign_key("fk_question_bank_course", "question_bank", "course", ["course_id"], ["course_id"], ondelete="RESTRICT")
    _drop_single_column_fk(bind, "question_import_job", "question_bank_id", "question_bank")
    op.create_foreign_key(
        "fk_question_import_bank_scope",
        "question_import_job",
        "question_bank",
        ["course_id", "question_bank_id"],
        ["course_id", "question_bank_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key("fk_question_lesson_authority", "question_lesson_map", "course_lesson", ["lesson_id"], ["lesson_id"], ondelete="RESTRICT")


def downgrade() -> None:
    op.drop_constraint("fk_question_lesson_authority", "question_lesson_map", type_="foreignkey")
    op.drop_constraint("fk_question_import_bank_scope", "question_import_job", type_="foreignkey")
    op.create_foreign_key(
        "fk_question_import_bank",
        "question_import_job",
        "question_bank",
        ["question_bank_id"],
        ["question_bank_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("fk_question_bank_course", "question_bank", type_="foreignkey")
    op.drop_constraint("uq_question_bank_scope", "question_bank", type_="unique")
    op.drop_constraint("fk_resource_delivery_course", "resource_delivery_manifest", type_="foreignkey")
    op.drop_constraint("fk_resource_quality_course", "resource_quality_check", type_="foreignkey")
    op.drop_constraint("fk_lesson_resource_course_lesson", "lesson_resource", type_="foreignkey")
    op.drop_constraint("fk_resource_course_lesson", "resource", type_="foreignkey")
    op.drop_constraint("fk_resource_course", "resource", type_="foreignkey")
    op.drop_constraint("fk_course_lesson_chapter_scope", "course_lesson", type_="foreignkey")
    op.create_foreign_key(
        "fk_course_lesson_chapter",
        "course_lesson",
        "course_chapter",
        ["chapter_id"],
        ["chapter_id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_course_lesson_code", "course_lesson", type_="unique")
    op.drop_constraint("uq_course_lesson_scope", "course_lesson", type_="unique")
    op.drop_constraint("uq_course_chapter_scope", "course_chapter", type_="unique")
    op.drop_column("course_lesson", "lesson_code")
