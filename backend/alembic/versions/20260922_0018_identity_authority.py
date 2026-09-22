"""add authoritative identity and roster reconciliation facts

Revision ID: 20260922_0018
Revises: 20260922_0017
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "20260922_0018"
down_revision = "20260922_0017"
branch_labels = None
depends_on = None


ROLE_ROWS = [
    {"role_id": "role_admin", "code": "admin", "name": "管理员", "created_at": datetime(2026, 9, 22)},
    {"role_id": "role_teacher", "code": "teacher", "name": "教师", "created_at": datetime(2026, 9, 22)},
    {"role_id": "role_student", "code": "student", "name": "学生", "created_at": datetime(2026, 9, 22)},
]

PERMISSION_ROWS = [
    ("perm_auth_accounts_read", "auth.accounts.read", "查看账号档案"),
    ("perm_auth_accounts_write", "auth.accounts.write", "创建账号档案"),
    ("perm_auth_reconciliation_scan", "auth.reconciliation.scan", "核对历史身份差异"),
    ("perm_teaching_course_read", "teaching.course.read", "查看课程"),
    ("perm_teaching_course_write", "teaching.course.write", "维护课程"),
    ("perm_teaching_class_read", "teaching.class.read", "查看班级"),
    ("perm_teaching_class_write", "teaching.class.write", "维护班级"),
    ("perm_teaching_members_read", "teaching.members.read", "查看学生名单"),
    ("perm_teaching_members_import", "teaching.members.import", "导入学生名单"),
    ("perm_teaching_members_write", "teaching.members.write", "维护学生名单"),
    ("perm_teaching_roster_freeze", "teaching.roster.freeze", "冻结学生名单"),
    ("perm_teaching_student_read", "teaching.student.read", "查看本人教学数据"),
    ("perm_teaching_attendance_read", "teaching.attendance.read", "查看签到"),
    ("perm_teaching_attendance_write", "teaching.attendance.write", "发布签到"),
    ("perm_teaching_attendance_sign", "teaching.attendance.sign", "学生签到"),
    ("perm_teaching_poll_read", "teaching.poll.read", "查看投票"),
    ("perm_teaching_poll_write", "teaching.poll.write", "发布投票"),
    ("perm_teaching_poll_answer", "teaching.poll.answer", "参与投票"),
    ("perm_teaching_assignment_write", "teaching.assignment.write", "发布作业"),
    ("perm_teaching_assignment_submit", "teaching.assignment.submit", "提交作业"),
    ("perm_teaching_quiz_write", "teaching.quiz.write", "发布测验"),
    ("perm_teaching_quiz_submit", "teaching.quiz.submit", "提交测验"),
    ("perm_teaching_dashboard_read", "teaching.dashboard.read", "查看教学看板"),
    ("perm_resources_read", "resources:read", "查看课程资源"),
    ("perm_resources_write", "resources:write", "维护课程资源"),
    ("perm_resources_review", "resources:review", "审核课程资源"),
    ("perm_resources_freeze", "resources:freeze", "冻结资源交付"),
    ("perm_resources_manage", "resources:manage", "管理全局课程资源"),
    ("perm_resources_all_courses", "resources:all-courses", "访问全部课程资源"),
    ("perm_labs_read", "labs.read", "查看实验定义"),
    ("perm_labs_write", "labs.write", "维护实验定义"),
    ("perm_labs_publish", "labs.publish", "发布实验"),
    ("perm_labs_knowledge_write", "labs.knowledge.write", "维护实验知识库"),
    ("perm_classroom_release_read", "classroom.release.read", "查看实验发布"),
    ("perm_classroom_runtime_remind", "classroom.runtime.remind", "提醒实验运行"),
    ("perm_classroom_runtime_rejudge", "classroom.runtime.rejudge", "重判实验运行"),
    ("perm_classroom_runtime_extend", "classroom.runtime.extend", "延长实验运行"),
    ("perm_classroom_runtime_unlock", "classroom.runtime.unlock", "解锁实验运行"),
    ("perm_classroom_runtime_rebuild", "classroom.runtime.rebuild", "重建实验运行"),
    ("perm_classroom_runtime_destroy", "classroom.runtime.destroy", "销毁实验运行"),
    ("perm_classroom_release_extend_all", "classroom.release.extend-all", "批量延长实验发布"),
    ("perm_classroom_release_remind_idle", "classroom.release.remind-idle", "提醒未开始实验"),
    ("perm_classroom_lab_start", "classroom.lab.start", "启动本人实验"),
    ("perm_classroom_lab_read", "classroom.lab.read", "查看本人实验"),
    ("perm_classroom_lab_submit", "classroom.lab.submit", "提交本人实验"),
    ("perm_classroom_terminal_use", "classroom.terminal.use", "使用本人实验终端"),
    ("perm_classroom_terminal_assist", "classroom.terminal.assist", "协助学生实验终端"),
    ("perm_classroom_logs_read", "classroom.logs.read", "查看实验日志"),
    ("perm_classroom_logs_download", "classroom.logs.download", "下载实验日志"),
    ("perm_classroom_logs_distribute", "classroom.logs.distribute", "分发实验日志"),
    ("perm_classroom_logs_assignment_read", "classroom.logs.assignment.read", "查看本人日志任务"),
    ("perm_classroom_logs_assignment_dl", "classroom.logs.assignment.download", "下载本人获准日志"),
    ("perm_classroom_readmodel_read", "classroom.readmodel.read", "查看课堂聚合数据"),
    ("perm_classroom_events_consume", "classroom.events.consume", "消费课堂事件（仅内部服务）"),
    ("perm_runtime_read", "runtime.read", "查看实验运行"),
    ("perm_runtime_start", "runtime.start", "启动实验运行"),
    ("perm_runtime_preview", "runtime.preview", "预览实验运行"),
    ("perm_runtime_destroy", "runtime.destroy", "销毁实验运行"),
    ("perm_runtime_rebuild", "runtime.rebuild", "重建实验运行"),
    ("perm_runtime_extend", "runtime.extend", "延长实验运行"),
    ("perm_runtime_rejudge", "runtime.rejudge", "重判实验运行"),
    ("perm_runtime_remind", "runtime.remind", "提醒实验运行"),
    ("perm_runtime_unlock", "runtime.unlock", "解锁实验运行"),
    ("perm_runtime_terminal", "runtime.terminal", "使用实验终端"),
    ("perm_runtime_submit", "runtime.submit", "提交实验运行"),
    ("perm_runtime_artifact_download", "runtime.distributed-artifact.download", "下载获准实验制品"),
    ("perm_infrastructure_read", "infrastructure.read", "查看基础设施"),
    ("perm_infrastructure_write", "infrastructure.write", "维护基础设施"),
    ("perm_grading_read", "grading:read", "查看成绩"),
    ("perm_grading_policy", "grading:policy", "维护评分策略"),
    ("perm_grading_recalculate", "grading:recalculate", "重算成绩"),
    ("perm_grading_post", "grading:post", "发布成绩"),
    ("perm_grading_all_courses", "grading:all-courses", "访问全部课程成绩"),
    ("perm_grading_all_classes", "grading:all-classes", "访问全部班级成绩"),
    ("perm_grading_consume", "grading:consume", "消费评分事件（仅内部服务）"),
    ("perm_analytics_class", "analytics:class", "查看班级学情"),
    ("perm_analytics_read", "analytics:read", "查看本人学情"),
    ("perm_archives_read", "archives:read", "查看教学归档"),
    ("perm_archives_write", "archives:write", "维护教学归档"),
    ("perm_archives_freeze", "archives:freeze", "冻结教学归档"),
    ("perm_audit_read", "audit:read", "查看审计记录"),
    ("perm_audit_ingest", "audit:ingest", "写入审计事件（仅内部服务）"),
    ("perm_integration_dispatch", "integration:dispatch", "派发集成事件（仅内部服务）"),
]

# 仅此白名单会写入普通账号角色；下列内部服务权限虽登记在权限目录中，
# 但不得通过管理员、教师或学生角色获得。
INTERNAL_ONLY_PERMISSION_CODES = {
    "audit:ingest",
    "classroom.events.consume",
    "grading:consume",
    "integration:dispatch",
}

ROLE_PERMISSION_CODES = {
    "admin": (
        "auth.accounts.read", "auth.accounts.write", "auth.reconciliation.scan",
        "resources:read", "resources:write", "resources:review", "resources:freeze", "resources:manage", "resources:all-courses",
        "runtime.read", "runtime.destroy", "runtime.rebuild", "runtime.extend", "runtime.rejudge", "runtime.remind", "runtime.unlock",
        "infrastructure.read", "infrastructure.write",
        "grading:read", "grading:policy", "grading:recalculate", "grading:post", "grading:all-courses", "grading:all-classes",
        "analytics:class", "analytics:read", "archives:read", "archives:write", "archives:freeze", "audit:read",
    ),
    "teacher": (
        "teaching.course.read", "teaching.course.write", "teaching.class.read", "teaching.class.write",
        "teaching.members.read", "teaching.members.import", "teaching.members.write", "teaching.roster.freeze",
        "teaching.attendance.read", "teaching.attendance.write", "teaching.poll.read", "teaching.poll.write",
        "teaching.assignment.write", "teaching.quiz.write", "teaching.dashboard.read",
        "resources:read", "resources:write", "resources:review", "resources:freeze",
        "labs.read", "labs.write", "labs.publish", "labs.knowledge.write",
        "classroom.release.read", "classroom.runtime.remind", "classroom.runtime.rejudge", "classroom.runtime.extend",
        "classroom.runtime.unlock", "classroom.runtime.rebuild", "classroom.runtime.destroy", "classroom.release.extend-all",
        "classroom.release.remind-idle", "classroom.terminal.assist", "classroom.logs.read", "classroom.logs.download",
        "classroom.logs.distribute", "classroom.readmodel.read",
        "runtime.read", "runtime.preview", "runtime.destroy", "runtime.rebuild", "runtime.extend", "runtime.rejudge",
        "runtime.remind", "runtime.unlock", "runtime.terminal",
        "grading:read", "grading:policy", "grading:recalculate", "grading:post", "analytics:class", "analytics:read",
        "archives:read", "archives:write", "archives:freeze", "audit:read",
    ),
    "student": (
        "teaching.course.read", "teaching.student.read", "teaching.attendance.sign", "teaching.poll.answer",
        "teaching.assignment.submit", "teaching.quiz.submit", "resources:read",
        "classroom.lab.start", "classroom.lab.read", "classroom.lab.submit", "classroom.terminal.use",
        "classroom.logs.assignment.read", "classroom.logs.assignment.download",
        "runtime.read", "runtime.start", "runtime.submit", "runtime.terminal",
        "grading:read", "analytics:read",
    ),
}


def upgrade() -> None:
    op.create_table(
        "auth_role",
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("role_id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "auth_permission",
        sa.Column("permission_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=96), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("permission_id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "auth_user",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("external_subject", sa.String(length=191), nullable=True),
        sa.Column("login_name", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("primary_role_code", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["primary_role_code"], ["auth_role.code"], name="fk_auth_user_primary_role", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("external_subject"),
        sa.UniqueConstraint("login_name"),
    )
    op.create_index("ix_auth_user_primary_role_code", "auth_user", ["primary_role_code"])
    op.create_table(
        "auth_user_role",
        sa.Column("auth_user_role_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["auth_role.role_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["auth_user.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("auth_user_role_id"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_auth_user_role"),
    )
    op.create_index("ix_auth_user_role_user_id", "auth_user_role", ["user_id"])
    op.create_index("ix_auth_user_role_role_id", "auth_user_role", ["role_id"])
    op.create_table(
        "auth_role_permission",
        sa.Column("auth_role_permission_id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("permission_id", sa.String(length=36), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["auth_permission.permission_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["auth_role.role_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("auth_role_permission_id"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_auth_role_permission"),
    )
    op.create_index("ix_auth_role_permission_role_id", "auth_role_permission", ["role_id"])
    op.create_index("ix_auth_role_permission_permission_id", "auth_role_permission", ["permission_id"])
    op.create_table(
        "teacher_profile",
        sa.Column("teacher_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("staff_number", sa.String(length=64), nullable=True),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["auth_user.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("teacher_id"),
        sa.UniqueConstraint("staff_number"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_teacher_profile_user_id", "teacher_profile", ["user_id"])
    op.create_table(
        "student_profile",
        sa.Column("student_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("student_number", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=80), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["auth_user.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("student_id"),
        sa.UniqueConstraint("student_number"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_student_profile_student_number", "student_profile", ["student_number"])
    op.create_index("ix_student_profile_user_id", "student_profile", ["user_id"])
    op.create_table(
        "identity_reconciliation_case",
        sa.Column("reconciliation_case_id", sa.String(length=36), nullable=False),
        sa.Column("legacy_student_id", sa.String(length=36), nullable=True),
        sa.Column("canonical_student_id", sa.String(length=36), nullable=True),
        sa.Column("class_id", sa.String(length=36), nullable=True),
        sa.Column("student_number", sa.String(length=64), nullable=False),
        sa.Column("observed_name", sa.String(length=80), nullable=True),
        sa.Column("observed_phone", sa.String(length=32), nullable=True),
        sa.Column("observed_email", sa.String(length=160), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_by", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("reconciliation_case_id"),
        sa.UniqueConstraint("legacy_student_id", "class_id", name="uq_identity_reconciliation_legacy_class"),
    )
    op.create_index("ix_identity_reconciliation_status_created", "identity_reconciliation_case", ["status", "created_at"])

    role_table = sa.table("auth_role", sa.column("role_id", sa.String), sa.column("code", sa.String), sa.column("name", sa.String), sa.column("created_at", sa.DateTime))
    permission_table = sa.table("auth_permission", sa.column("permission_id", sa.String), sa.column("code", sa.String), sa.column("name", sa.String), sa.column("created_at", sa.DateTime))
    mapping_table = sa.table("auth_role_permission", sa.column("auth_role_permission_id", sa.String), sa.column("role_id", sa.String), sa.column("permission_id", sa.String), sa.column("assigned_at", sa.DateTime))
    stamp = datetime(2026, 9, 22)
    op.bulk_insert(role_table, ROLE_ROWS)
    op.bulk_insert(permission_table, [{"permission_id": item[0], "code": item[1], "name": item[2], "created_at": stamp} for item in PERMISSION_ROWS])
    permission_ids_by_code = {code: permission_id for permission_id, code, _name in PERMISSION_ROWS}
    mapped_codes = {code for codes in ROLE_PERMISSION_CODES.values() for code in codes}
    missing_codes = mapped_codes.difference(permission_ids_by_code)
    if missing_codes:
        raise ValueError(f"0018 角色权限映射引用了未登记权限：{sorted(missing_codes)}")
    forbidden_codes = mapped_codes.intersection(INTERNAL_ONLY_PERMISSION_CODES)
    if forbidden_codes:
        raise ValueError(f"0018 不得把内部服务权限授予普通角色：{sorted(forbidden_codes)}")
    mappings = [
        {
            "auth_role_permission_id": f"arp_{role_code}_{index:03d}",
            "role_id": f"role_{role_code}",
            "permission_id": permission_ids_by_code[permission_code],
            "assigned_at": stamp,
        }
        for role_code, permission_codes in ROLE_PERMISSION_CODES.items()
        for index, permission_code in enumerate(permission_codes, 1)
    ]
    op.bulk_insert(mapping_table, mappings)


def downgrade() -> None:
    op.drop_index("ix_identity_reconciliation_status_created", table_name="identity_reconciliation_case")
    op.drop_table("identity_reconciliation_case")
    op.drop_index("ix_student_profile_user_id", table_name="student_profile")
    op.drop_index("ix_student_profile_student_number", table_name="student_profile")
    op.drop_table("student_profile")
    op.drop_index("ix_teacher_profile_user_id", table_name="teacher_profile")
    op.drop_table("teacher_profile")
    op.drop_index("ix_auth_role_permission_permission_id", table_name="auth_role_permission")
    op.drop_index("ix_auth_role_permission_role_id", table_name="auth_role_permission")
    op.drop_table("auth_role_permission")
    op.drop_index("ix_auth_user_role_role_id", table_name="auth_user_role")
    op.drop_index("ix_auth_user_role_user_id", table_name="auth_user_role")
    op.drop_table("auth_user_role")
    op.drop_index("ix_auth_user_primary_role_code", table_name="auth_user")
    op.drop_table("auth_user")
    op.drop_table("auth_permission")
    op.drop_table("auth_role")
