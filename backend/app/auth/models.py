from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base


class AuthRole(Base):
    __tablename__ = "auth_role"

    role_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AuthPermission(Base):
    __tablename__ = "auth_permission"

    permission_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(96), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AuthUser(Base):
    __tablename__ = "auth_user"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    external_subject: Mapped[str | None] = mapped_column(String(191), unique=True, nullable=True)
    login_name: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    primary_role_code: Mapped[str] = mapped_column(String(32), ForeignKey("auth_role.code", ondelete="RESTRICT"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class AuthUserRole(Base):
    __tablename__ = "auth_user_role"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_auth_user_role"),)

    auth_user_role_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_user.user_id", ondelete="RESTRICT"), index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("auth_role.role_id", ondelete="RESTRICT"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime)


class AuthRolePermission(Base):
    __tablename__ = "auth_role_permission"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_auth_role_permission"),)

    auth_role_permission_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("auth_role.role_id", ondelete="RESTRICT"), index=True)
    permission_id: Mapped[str] = mapped_column(ForeignKey("auth_permission.permission_id", ondelete="RESTRICT"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime)


class TeacherProfile(Base):
    __tablename__ = "teacher_profile"

    teacher_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_user.user_id", ondelete="RESTRICT"), unique=True, index=True)
    staff_number: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class StudentProfile(Base):
    __tablename__ = "student_profile"

    student_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_user.user_id", ondelete="RESTRICT"), unique=True, index=True)
    student_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class IdentityReconciliationCase(Base):
    """保留旧学生标识与冲突证据；本轮不改写历史事实表。"""

    __tablename__ = "identity_reconciliation_case"
    __table_args__ = (
        UniqueConstraint("legacy_student_id", "class_id", name="uq_identity_reconciliation_legacy_class"),
        Index("ix_identity_reconciliation_status_created", "status", "created_at"),
    )

    reconciliation_case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    legacy_student_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    canonical_student_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    class_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    student_number: Mapped[str] = mapped_column(String(64))
    observed_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    observed_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    details_json: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
