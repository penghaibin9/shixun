"""add web course authority and challenge training facts

Revision ID: 20260925_0021
Revises: 20260922_0020
"""

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "20260925_0021"
down_revision = "20260922_0020"
branch_labels = None
depends_on = None

COURSE_ID = "course_web_security"
THEORY = [
    ("1.1", "Web 安全与 HTTP 攻击面"),
    ("1.2", "身份认证、会话与访问控制"),
    ("1.3", "输入验证与 SQL 注入原理"),
    ("1.4", "XSS 与浏览器信任边界"),
    ("1.5", "文件上传与路径安全"),
    ("1.6", "SSRF 与服务端网络边界"),
    ("1.7", "XML、反序列化与数据解析风险"),
    ("1.8", "API 安全与对象级授权"),
    ("1.9", "安全响应头、Cookie 与浏览器防护"),
    ("1.10", "日志、审计与 Web 攻击检测"),
    ("1.11", "漏洞修复验证与回归测试"),
    ("1.12", "Web 安全综合攻防与复盘"),
]
LABS = [
    ("实验01", "HTTP 请求观察与安全基线"),
    ("实验02", "认证与对象授权验证"),
    ("实验03", "SQL 注入原理与参数化修复"),
    ("实验04", "XSS 输入输出边界"),
    ("实验05", "文件上传与路径穿越防护"),
    ("实验06", "SSRF 出口控制"),
    ("实验07", "XML 解析与安全配置"),
    ("实验08", "API 对象级权限测试"),
    ("实验09", "Cookie 与安全响应头配置"),
    ("实验10", "Web 日志检测与攻击链回放"),
    ("实验11", "漏洞修复回归门禁"),
    ("实验12", "Web 综合靶场挑战"),
]


def _id(kind: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"yueke:{COURSE_ID}:{kind}:{key}"))


def upgrade() -> None:
    op.create_table(
        "challenge_definition",
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("lesson_id", sa.String(length=36), nullable=False),
        sa.Column("lab_definition_id", sa.String(length=36), nullable=True),
        sa.Column("checkpoint_key", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.String(length=24), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["course_id", "lesson_id"], ["course_lesson.course_id", "course_lesson.lesson_id"], name="fk_challenge_course_lesson", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lab_definition_id"], ["lab_definition.lab_definition_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("challenge_id"),
    )
    op.create_index("ix_challenge_course_status", "challenge_definition", ["course_id", "status"])
    op.create_table(
        "challenge_hint",
        sa.Column("hint_id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("unlock_after_attempts", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenge_definition.challenge_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("hint_id"),
        sa.UniqueConstraint("challenge_id", "sequence", name="uq_challenge_hint_sequence"),
    )
    op.create_index("ix_challenge_hint_challenge_id", "challenge_hint", ["challenge_id"])
    op.create_table(
        "challenge_flag",
        sa.Column("flag_id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("salt", sa.String(length=64), nullable=False),
        sa.Column("flag_hash", sa.String(length=64), nullable=False),
        sa.Column("case_sensitive", sa.Boolean(), nullable=False),
        sa.Column("configured_by", sa.String(length=36), nullable=False),
        sa.Column("configured_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenge_definition.challenge_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("flag_id"),
        sa.UniqueConstraint("challenge_id", name="uq_challenge_flag_challenge"),
    )
    op.create_table(
        "challenge_attempt",
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("student_id", sa.String(length=36), nullable=False),
        sa.Column("class_id", sa.String(length=36), nullable=False),
        sa.Column("lab_release_id", sa.String(length=36), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenge_definition.challenge_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_id"], ["class.class_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lab_release_id"], ["lab_release.lab_release_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint("challenge_id", "student_id", "attempt_no", name="uq_challenge_student_attempt"),
    )
    op.create_index("ix_challenge_attempt_scope", "challenge_attempt", ["challenge_id", "student_id", "created_at"])

    bind = op.get_bind()
    exists = bind.execute(sa.text("SELECT 1 FROM course WHERE course_id=:course_id"), {"course_id": COURSE_ID}).first()
    if not exists:
        bind.execute(sa.text(
            """INSERT INTO course (course_id,name,term,owner_teacher_id,major,description,status,created_at)
               VALUES (:course_id,:name,:term,:owner,:major,:description,:status,:created_at)"""
        ), {
            "course_id": COURSE_ID,
            "name": "Web 应用安全实训",
            "term": "2026 秋季",
            "owner": "system_content_pack",
            "major": "网络空间安全",
            "description": "跃科原创中文 Web 安全课程；第三方靶场作为独立依赖，经许可证、安全审查和镜像摘要冻结后接入。",
            "status": "ACTIVE",
            "created_at": datetime.utcnow(),
        })

    theory_chapter = _id("chapter", "web-theory")
    lab_chapter = _id("chapter", "web-labs")
    for chapter_id, title, sequence in [(theory_chapter, "Web 安全理论", 1), (lab_chapter, "Web 安全实验", 2)]:
        bind.execute(sa.text(
            """INSERT IGNORE INTO course_chapter (chapter_id,course_id,title,sequence)
               VALUES (:chapter_id,:course_id,:title,:sequence)"""
        ), {"chapter_id": chapter_id, "course_id": COURSE_ID, "title": title, "sequence": sequence})

    lesson_rows = [(code, title, "THEORY", theory_chapter, int(code.split(".", 1)[1])) for code, title in THEORY]
    lesson_rows += [(code, title, "LAB", lab_chapter, int("".join(ch for ch in code if ch.isdigit()))) for code, title in LABS]
    for code, title, kind, chapter_id, sequence in lesson_rows:
        lesson_id = _id("lesson", f"web:{code}")
        bind.execute(sa.text(
            """INSERT IGNORE INTO course_lesson (lesson_id,course_id,chapter_id,lesson_code,title,sequence,lesson_type)
               VALUES (:lesson_id,:course_id,:chapter_id,:lesson_code,:title,:sequence,:lesson_type)"""
        ), {
            "lesson_id": lesson_id, "course_id": COURSE_ID, "chapter_id": chapter_id,
            "lesson_code": code, "title": title, "sequence": sequence, "lesson_type": kind,
        })
        bind.execute(sa.text(
            """INSERT IGNORE INTO lesson_resource
               (lesson_resource_id,course_id,lesson_id,purpose,environment,principle,steps_summary,core_experiment,linked_file_pack_id,linked_video_resource_id,linked_lab_definition_id)
               VALUES (:rid,:course_id,:lesson_id,:purpose,:environment,:principle,:steps_summary,:core_experiment,NULL,NULL,NULL)"""
        ), {
            "rid": _id("lesson-resource", code), "course_id": COURSE_ID, "lesson_id": lesson_id,
            "purpose": f"掌握{title}的核心概念与验证方法。",
            "environment": "实验课时由隔离 LabDefinition 提供环境；理论课时不要求运行环境。" if kind == "THEORY" else "隔离网络中的学生操作节点与教学靶场节点。",
            "principle": "所有操作限定在授权教学环境，验证同时覆盖允许路径和拒绝路径。",
            "steps_summary": "理解目标、执行验证、收集证据、完成复盘。" if kind == "LAB" else None,
            "core_experiment": title if kind == "LAB" else None,
        })

    for index, (code, title) in enumerate(LABS, start=1):
        challenge_id = f"challenge_web_{index:02d}"
        lesson_id = _id("lesson", f"web:{code}")
        bind.execute(sa.text(
            """INSERT IGNORE INTO challenge_definition
               (challenge_id,course_id,lesson_id,lab_definition_id,checkpoint_key,title,description,difficulty,max_attempts,status,created_by,created_at,published_at)
               VALUES (:challenge_id,:course_id,:lesson_id,NULL,NULL,:title,:description,:difficulty,10,'DRAFT','system_content_pack',:created_at,NULL)"""
        ), {
            "challenge_id": challenge_id, "course_id": COURSE_ID, "lesson_id": lesson_id,
            "title": title, "description": f"{title}：在授权隔离实验环境中完成阶段目标并通过 Checkpoint/Flag 验证。",
            "difficulty": "INTERMEDIATE" if index >= 10 else "BEGINNER", "created_at": datetime.utcnow(),
        })
        hint_rows = [
            (1, "先确认实验目标", "先查看实验说明、节点拓扑和当前 Checkpoint，确认需要证明的安全事实。", 1),
            (2, "从证据反推问题", "优先观察请求、响应、日志或配置差异，不要在未理解边界时反复尝试。", 3),
        ]
        for seq, hint_title, content, unlock in hint_rows:
            bind.execute(sa.text(
                """INSERT IGNORE INTO challenge_hint
                   (hint_id,challenge_id,sequence,title,content,unlock_after_attempts,created_by,created_at)
                   VALUES (:hint_id,:challenge_id,:sequence,:title,:content,:unlock,'system_content_pack',:created_at)"""
            ), {
                "hint_id": f"hint_web_{index:02d}_{seq}", "challenge_id": challenge_id, "sequence": seq,
                "title": hint_title, "content": content, "unlock": unlock, "created_at": datetime.utcnow(),
            })


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM challenge_hint WHERE challenge_id LIKE 'challenge_web_%'"))
    bind.execute(sa.text("DELETE FROM challenge_definition WHERE course_id=:course_id"), {"course_id": COURSE_ID})
    bind.execute(sa.text("DELETE FROM lesson_resource WHERE course_id=:course_id"), {"course_id": COURSE_ID})
    bind.execute(sa.text("DELETE FROM course_lesson WHERE course_id=:course_id"), {"course_id": COURSE_ID})
    bind.execute(sa.text("DELETE FROM course_chapter WHERE course_id=:course_id"), {"course_id": COURSE_ID})
    bind.execute(sa.text("DELETE FROM course WHERE course_id=:course_id AND owner_teacher_id='system_content_pack'"), {"course_id": COURSE_ID})
    op.drop_index("ix_challenge_attempt_scope", table_name="challenge_attempt")
    op.drop_table("challenge_attempt")
    op.drop_table("challenge_flag")
    op.drop_index("ix_challenge_hint_challenge_id", table_name="challenge_hint")
    op.drop_table("challenge_hint")
    op.drop_index("ix_challenge_course_status", table_name="challenge_definition")
    op.drop_table("challenge_definition")
