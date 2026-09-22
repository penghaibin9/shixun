from datetime import datetime
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import models as auth
from app.common.context import (
    RequestStateTrustedIdentityResolver,
    TrustedIdentity,
    configure_trusted_identity_resolver,
)
from app.common.models import Base, DomainEventOutbox
from app.database import get_session
from app.lab_classroom.gateway import ContractClient, GatewayBundle, get_gateways
from app.labs.database import get_session as get_labs_session
from app.main import app
from app.teaching import models as teaching
from app.teaching.xlsx import HEADERS
from backend.tests.auth_profiles import ROLE_IDS, seed_reference_roles, seed_student_profile


def headers(*permissions: str, course_id: str = "", class_id: str = "", role: str = "teacher", user_id: str = "teacher-test", teacher_id: str = "teacher-test"):
    result = {"X-User-Id": user_id, "X-Role": role, "X-Permissions": ",".join(permissions)}
    if teacher_id:
        result["X-Teacher-Id"] = teacher_id
    if course_id:
        result["X-Course-Ids"] = course_id
    if class_id:
        result["X-Class-Ids"] = class_id
    return result


def workbook(rows) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


@pytest.fixture()
def test_database():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override
    # 实验定义和运行时路由复用该数据库连接；测试不能悄悄落到默认本地库。
    app.dependency_overrides[get_labs_session] = override
    configure_trusted_identity_resolver(app, RequestStateTrustedIdentityResolver())
    yield TestClient(app), sessions
    configure_trusted_identity_resolver(app, RequestStateTrustedIdentityResolver())
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def create_course_and_class(client: TestClient, *, name: str = "身份核验班"):
    teacher = headers("teaching.course.write")
    course = client.post("/api/v1/courses", headers=teacher, json={"name": f"身份权威课程-{name}", "term": "2026 秋季"})
    assert course.status_code == 201, course.text
    course_id = course.json()["course_id"]
    classroom = client.post(
        "/api/v1/classes",
        headers=headers("teaching.class.write", course_id=course_id),
        json={"name": name, "term": "2026 秋季", "course_id": course_id},
    )
    assert classroom.status_code == 201, classroom.text
    return course_id, classroom.json()["class_id"]


def test_default_environment_does_not_trust_browser_identity_headers(monkeypatch):
    monkeypatch.delenv("YUEKE_ENV", raising=False)
    monkeypatch.delenv("YUEKE_ALLOW_DEV_IDENTITY_HEADERS", raising=False)
    response = TestClient(app).get(
        "/api/v1/auth/context",
        headers={"X-User-Id": "forged-admin", "X-Role": "admin", "X-Permissions": "auth.accounts.write"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH.TRUSTED_IDENTITY_REQUIRED"


def test_trusted_subject_derives_role_permissions_and_scope_from_authoritative_tables(test_database):
    client, sessions = test_database
    with sessions() as db:
        stamp = datetime.utcnow()
        seed_reference_roles(db)
        db.add(auth.AuthPermission(permission_id="perm_course_read", code="teaching.course.read", name="查看课程", created_at=stamp))
        db.add(auth.AuthRolePermission(auth_role_permission_id="arp_teacher_course_read", role_id=ROLE_IDS["teacher"], permission_id="perm_course_read", assigned_at=stamp))
        db.add(auth.AuthUser(user_id="auth-teacher", external_subject="sso:teacher-1", login_name="teacher-1", display_name="权威教师", status="ACTIVE", primary_role_code="teacher", created_at=stamp, updated_at=stamp))
        db.add(auth.AuthUserRole(auth_user_role_id="aur-teacher", user_id="auth-teacher", role_id=ROLE_IDS["teacher"], assigned_at=stamp))
        db.add(auth.TeacherProfile(teacher_id="teacher-authoritative", user_id="auth-teacher", staff_number="T-001", display_name="权威教师", status="ACTIVE", created_at=stamp, updated_at=stamp))
        db.add(teaching.Course(course_id="course-authoritative", name="权威课程", term="2026 秋季", owner_teacher_id="teacher-authoritative", major=None, description=None, status="ACTIVE", created_at=stamp))
        db.add(teaching.TeachingClass(class_id="class-authoritative", name="权威班", term="2026 秋季", owner_teacher_id="teacher-authoritative", created_at=stamp, roster_frozen_at=None, roster_frozen_by=None, roster_snapshot_hash=None))
        db.add(teaching.TeachingTeacherAssignment(assignment_id="assignment-authoritative", teacher_id="teacher-authoritative", class_id="class-authoritative", course_id="course-authoritative"))
        db.commit()

    class Resolver:
        def resolve(self, request):
            return TrustedIdentity(external_subject="sso:teacher-1")

    configure_trusted_identity_resolver(app, Resolver())
    response = client.get(
        "/api/v1/auth/context",
        headers={"X-User-Id": "forged-admin", "X-Role": "admin", "X-Permissions": "auth.accounts.write"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "user_id": "auth-teacher",
        "role": "teacher",
        "teacher_id": "teacher-authoritative",
        "student_id": None,
        "permissions": ["teaching.course.read"],
        "course_ids": ["course-authoritative"],
        "class_ids": ["class-authoritative"],
    }


def _identity_migration_module():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260922_0018_identity_authority.py"
    spec = spec_from_file_location("identity_authority_migration", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _grant_role_permissions(db, role_code: str, permission_codes: set[str]) -> None:
    stamp = datetime.utcnow()
    for index, code in enumerate(sorted(permission_codes), 1):
        permission = db.scalar(select(auth.AuthPermission).where(auth.AuthPermission.code == code))
        if permission is None:
            permission = auth.AuthPermission(permission_id=f"trusted-{sha256(code.encode()).hexdigest()[:24]}", code=code, name=code, created_at=stamp)
            db.add(permission)
            db.flush()
        db.add(
            auth.AuthRolePermission(
                auth_role_permission_id=f"trusted-{role_code}-mapping-{index}",
                role_id=ROLE_IDS[role_code],
                permission_id=permission.permission_id,
                assigned_at=stamp,
            )
        )


def test_0018_registers_interactive_permissions_without_granting_internal_service_permissions():
    migration = _identity_migration_module()
    registered = {code for _permission_id, code, _name in migration.PERMISSION_ROWS}
    mapped = {role: set(codes) for role, codes in migration.ROLE_PERMISSION_CODES.items()}

    assert {
        "resources:read", "resources:write", "resources:review", "resources:freeze",
        "labs.read", "labs.write", "labs.publish", "labs.knowledge.write",
        "classroom.release.read", "classroom.lab.start", "classroom.lab.read", "classroom.lab.submit",
        "runtime.read", "runtime.start", "runtime.submit", "runtime.terminal",
        "grading:read", "analytics:class", "archives:read", "audit:read",
        "infrastructure.read", "infrastructure.write",
    }.issubset(registered)
    assert {"resources:read", "labs.read", "classroom.release.read", "grading:read", "archives:freeze"}.issubset(mapped["teacher"])
    assert {"resources:read", "classroom.lab.start", "classroom.lab.read", "classroom.lab.submit", "runtime.start", "runtime.submit", "grading:read"}.issubset(mapped["student"])
    assert {"resources:manage", "infrastructure.write", "grading:all-courses", "audit:read"}.issubset(mapped["admin"])
    assert set(migration.INTERNAL_ONLY_PERMISSION_CODES).issubset(registered)
    assert not set(migration.INTERNAL_ONLY_PERMISSION_CODES).intersection(set().union(*mapped.values()))
    assert all(len(permission_id) <= 36 for permission_id, _code, _name in migration.PERMISSION_ROWS)


def test_trusted_profiles_reach_teacher_resources_labs_and_student_classroom_runtime(test_database):
    client, sessions = test_database
    teacher_permissions = {
        "resources:read", "labs.read", "classroom.release.read", "runtime.read", "grading:read", "archives:read",
    }
    student_permissions = {
        "classroom.lab.start", "classroom.lab.read", "classroom.lab.submit", "classroom.terminal.use",
        "runtime.read", "runtime.start", "runtime.submit", "runtime.terminal", "grading:read", "analytics:read",
    }
    with sessions() as db:
        stamp = datetime.utcnow()
        seed_reference_roles(db)
        _grant_role_permissions(db, "teacher", teacher_permissions)
        _grant_role_permissions(db, "student", student_permissions)
        db.add_all([
            auth.AuthUser(user_id="trusted-teacher-user", external_subject="sso:coverage-teacher", login_name="coverage-teacher", display_name="可信教师", status="ACTIVE", primary_role_code="teacher", created_at=stamp, updated_at=stamp),
            auth.AuthUser(user_id="trusted-student-user", external_subject="sso:coverage-student", login_name="coverage-student", display_name="可信学生", status="ACTIVE", primary_role_code="student", created_at=stamp, updated_at=stamp),
            auth.AuthUserRole(auth_user_role_id="trusted-teacher-role", user_id="trusted-teacher-user", role_id=ROLE_IDS["teacher"], assigned_at=stamp),
            auth.AuthUserRole(auth_user_role_id="trusted-student-role", user_id="trusted-student-user", role_id=ROLE_IDS["student"], assigned_at=stamp),
            auth.TeacherProfile(teacher_id="trusted-teacher", user_id="trusted-teacher-user", staff_number="T-COVERAGE", display_name="可信教师", status="ACTIVE", created_at=stamp, updated_at=stamp),
            auth.StudentProfile(student_id="trusted-student", user_id="trusted-student-user", student_number="20269901", full_name="可信学生", phone=None, email=None, status="ACTIVE", created_at=stamp, updated_at=stamp),
            teaching.Course(course_id="trusted-course", name="可信课程", term="2026 秋季", owner_teacher_id="trusted-teacher", major=None, description=None, status="ACTIVE", created_at=stamp),
            teaching.TeachingClass(class_id="trusted-class", name="可信班级", term="2026 秋季", owner_teacher_id="trusted-teacher", created_at=stamp, roster_frozen_at=None, roster_frozen_by=None, roster_snapshot_hash=None),
            teaching.ClassCourse(class_course_id="trusted-class-course", class_id="trusted-class", course_id="trusted-course"),
            teaching.TeachingTeacherAssignment(assignment_id="trusted-assignment", teacher_id="trusted-teacher", class_id="trusted-class", course_id="trusted-course"),
            teaching.ClassMembership(class_membership_id="trusted-membership", class_id="trusted-class", student_id="trusted-student", student_number="20269901", student_name="可信学生", phone=None, email=None, status="ACTIVE", joined_at=stamp),
        ])
        db.commit()

    class Resolver:
        subject = "sso:coverage-teacher"

        def resolve(self, request):
            return TrustedIdentity(external_subject=self.subject)

    resolver = Resolver()
    configure_trusted_identity_resolver(app, resolver)
    app.dependency_overrides[get_gateways] = lambda: GatewayBundle(
        runtime=ContractClient("D 实验运行", None),
        teaching=ContractClient("A 教学核心", None),
        grading=ContractClient("F 成绩审计", None),
    )

    teacher_context = client.get("/api/v1/auth/context", headers={"X-Role": "admin", "X-Permissions": "infrastructure.write"})
    assert teacher_context.status_code == 200, teacher_context.text
    assert {"resources:read", "labs.read"}.issubset(set(teacher_context.json()["permissions"]))
    resources = client.get("/api/v1/resources", params={"course_id": "trusted-course"})
    assert resources.status_code == 200, resources.text
    labs = client.get("/api/v1/labs")
    assert labs.status_code == 200, labs.text

    resolver.subject = "sso:coverage-student"
    student_context = client.get("/api/v1/auth/context")
    assert student_context.status_code == 200, student_context.text
    assert {"classroom.lab.start", "runtime.start", "runtime.read"}.issubset(set(student_context.json()["permissions"]))
    classroom = client.post("/api/v1/classroom/my/lab-releases/missing-release/start")
    assert classroom.status_code == 503
    assert classroom.json()["code"] == "DEPENDENCY.PENDING"
    runtime = client.get("/api/v1/runtime/requests/missing-request")
    assert runtime.status_code == 404
    assert runtime.json()["code"] == "RUNTIME.REQUEST_NOT_FOUND"


def test_admin_can_create_and_query_student_profile_without_credentials(test_database):
    client, sessions = test_database
    with sessions() as db:
        seed_reference_roles(db)
        db.commit()
    admin = headers("auth.accounts.write", "auth.accounts.read", role="admin", user_id="admin-test", teacher_id="")
    created = client.post(
        "/api/v1/auth/users",
        headers=admin,
        json={"display_name": "张同学", "role": "student", "login_name": "student-20260001", "student_number": "20260001", "email": "zhang@example.edu.cn"},
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["student_number"] == "20260001"
    assert payload["student_id"]
    assert "password" not in payload
    queried = client.get(f"/api/v1/auth/users/{payload['user_id']}", headers=admin)
    assert queried.status_code == 200
    listed = client.get("/api/v1/auth/users", headers=admin, params={"search": "张", "role": "student"})
    assert listed.status_code == 200 and listed.json()["total"] == 1
    missing_auth_identity = client.post(
        "/api/v1/auth/users",
        headers=admin,
        json={"display_name": "无认证标识学生", "role": "student", "student_number": "20260002"},
    )
    assert missing_auth_identity.status_code == 422
    duplicate = client.post(
        "/api/v1/auth/users",
        headers=admin,
        json={"display_name": "重复学号", "role": "student", "login_name": "student-20260001-duplicate", "student_number": "20260001"},
    )
    assert duplicate.status_code == 409
    with sessions() as db:
        assert db.scalar(select(auth.StudentProfile.student_id).where(auth.StudentProfile.student_number == "20260001")) == payload["student_id"]
        assert db.scalar(select(DomainEventOutbox.event_type).where(DomainEventOutbox.event_type == "auth.account.created")) == "auth.account.created"


def test_roster_uses_canonical_profiles_and_records_identity_conflicts_without_rewrite(test_database):
    client, sessions = test_database
    with sessions() as db:
        seed_student_profile(db, student_id="student-canonical", student_number="20260001", full_name="张三", phone="13800000000")
        seed_student_profile(db, student_id="student-disabled", student_number="20260002", full_name="李四", status="DISABLED")
        seed_student_profile(db, student_id="student-name-check", student_number="20260003", full_name="王五")
        db.commit()
    course_id, class_one = create_course_and_class(client, name="身份核验一班")
    _, class_two = create_course_and_class(client, name="身份核验二班")
    roster = headers("teaching.members.import", "teaching.members.read", "teaching.members.write", course_id=course_id, class_id=class_one)
    imported = client.post(
        f"/api/v1/classes/{class_one}/members/import",
        headers={**roster, "Idempotency-Key": "identity-roster-one"},
        files={"file": ("students.xlsx", workbook([
            ["20260001", "张三", "身份核验一班", "", ""],
            ["20269999", "未知学生", "身份核验一班", "", ""],
            ["20260002", "李四", "身份核验一班", "", ""],
            ["20260003", "错误姓名", "身份核验一班", "", ""],
        ]))},
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["success_count"] == 1
    assert imported.json()["failure_count"] == 3
    reasons = {row["student_number"]: row["reason"] for row in imported.json()["error_rows_json"]}
    assert "学号不存在" in reasons["20269999"]
    assert "账号不可用" in reasons["20260002"]
    assert "姓名与已有学生档案不一致" in reasons["20260003"]

    second_class_roster = headers("teaching.members.import", "teaching.members.read", course_id=course_id, class_id=class_two)
    second = client.post(
        f"/api/v1/classes/{class_two}/members/import",
        headers={**second_class_roster, "Idempotency-Key": "identity-roster-two"},
        files={"file": ("students.xlsx", workbook([["20260001", "张三", "身份核验二班", "", ""]]))},
    )
    assert second.status_code == 201, second.text
    assert second.json()["success_count"] == 1
    forged_member_id = client.post(
        f"/api/v1/classes/{class_two}/members",
        headers={**second_class_roster, "X-Permissions": "teaching.members.write"},
        json={"student_id": "forged", "student_number": "20260001", "student_name": "张三"},
    )
    assert forged_member_id.status_code == 422

    _, historical_class = create_course_and_class(client, name="历史名单班")
    with sessions() as db:
        db.add(teaching.ClassMembership(
            class_membership_id="legacy-membership",
            class_id=historical_class,
            student_id="legacy-student-id",
            student_number="20260001",
            student_name="张三",
            phone=None,
            email=None,
            status="ACTIVE",
            joined_at=datetime.utcnow(),
        ))
        db.commit()
    admin = headers("auth.reconciliation.scan", role="admin", user_id="admin-test", teacher_id="")
    scanned = client.post("/api/v1/auth/reconciliation/scan", headers=admin)
    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["created_case_count"] == 1
    repeated_scan = client.post("/api/v1/auth/reconciliation/scan", headers=admin)
    assert repeated_scan.status_code == 200, repeated_scan.text
    assert repeated_scan.json()["created_case_count"] == 0
    assert repeated_scan.json()["existing_case_count"] == 1
    with sessions() as db:
        memberships = list(db.scalars(select(teaching.ClassMembership).where(teaching.ClassMembership.student_number == "20260001").order_by(teaching.ClassMembership.class_id)))
        assert {member.student_id for member in memberships} == {"student-canonical", "legacy-student-id"}
        cases = list(db.scalars(select(auth.IdentityReconciliationCase)))
        assert {case.reason_code for case in cases} >= {"STUDENT_PROFILE_NOT_FOUND", "STUDENT_PROFILE_DISABLED", "STUDENT_NAME_CONFLICT", "MEMBERSHIP_IDENTITY_CONFLICT"}
        assert any(case.legacy_student_id == "legacy-student-id" and case.canonical_student_id == "student-canonical" for case in cases)
