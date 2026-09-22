from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.common.context import UserContext
from app.common.models import FileObject
from app.common.outbox import enqueue_event
from app.resources.models import LessonResource, Question, QuestionLessonMap
from app.teaching.models import CourseLesson

from .database import create_session_factory
from .formal_catalog import COURSE_ID, formal_definition_records
from .models import LabDefinition, LabExplainDiagram, LabKnowledgePoint, LabQuestionKnowledgeMap, LabTemplate, LabVersion
from .service import LabService


DIAGRAM = Path(__file__).with_name("fixtures") / "rsa-signature-flow.svg"
SEED_USER_ID = "user_seed_c"


def seed_formal_lab_definitions() -> dict[str, int]:
    """Create the frozen 12-lab catalog without overwriting conflicting content."""
    session = create_session_factory()()
    context = UserContext(
        user_id=SEED_USER_ID,
        role="teacher",
        teacher_id="teacher_seed_c",
        student_id=None,
        permissions=frozenset({"labs.read", "labs.write", "labs.publish", "labs.knowledge.write"}),
        course_ids=frozenset({COURSE_ID}),
        class_ids=frozenset(),
    )
    created_count = 0
    linked_count = 0
    try:
        records = formal_definition_records()
        authority = list(
            session.scalars(
                select(CourseLesson).where(
                    CourseLesson.course_id == COURSE_ID,
                    CourseLesson.lesson_type == "LAB",
                )
            )
        )
        authority_by_id = {lesson.lesson_id: lesson for lesson in authority}
        if len(authority_by_id) != 12:
            raise RuntimeError("A 模块权威目录不是 12 个实验课时，拒绝导入正式实验定义")
        extensions = list(session.scalars(select(LessonResource).where(LessonResource.course_id == COURSE_ID)))
        extension_by_lesson = {item.lesson_id: item for item in extensions}
        service = LabService(session, context)
        _ensure_templates(session)

        for record in records:
            data = record["create"]
            authority_lesson = authority_by_id.get(record["lesson_id"])
            extension = extension_by_lesson.get(record["lesson_id"])
            if not authority_lesson or authority_lesson.lesson_code != record["lesson_code"]:
                raise RuntimeError(f"A 模块权威课时与正式实验定义不一致：{record['lesson_code']}")
            if not extension:
                raise RuntimeError(f"B 模块课程资源扩展不存在：{record['lesson_code']}")

            existing = session.get(LabDefinition, data.spec.lab_definition_id)
            if existing:
                frozen_v1 = session.scalar(
                    select(LabVersion).where(
                        LabVersion.lab_definition_id == existing.lab_definition_id,
                        LabVersion.version == 1,
                    )
                )
                expected_spec = data.spec.model_dump(mode="json")
                if (
                    existing.course_id != data.course_id
                    or existing.code != data.code
                    or existing.name != data.spec.name
                    or existing.category != data.category
                    or existing.objective != data.objective
                    or not frozen_v1
                    or frozen_v1.status != "PUBLISHED"
                    or frozen_v1.spec_json != expected_spec
                ):
                    raise RuntimeError(f"已有实验定义与正式 v1.0.0 内容冲突，拒绝覆盖：{existing.lab_definition_id}")
            else:
                created = service.create_lab(data, f"formal-lab-create-v1:{data.spec.lab_definition_id}")
                version_id = created["latest_version"]["lab_version_id"]
                service.validate_version(version_id, f"formal-lab-validate-v1:{data.spec.lab_definition_id}")
                service.publish_version(version_id, f"formal-lab-publish-v1:{data.spec.lab_definition_id}")
                created_count += 1

            if extension.linked_lab_definition_id not in (None, data.spec.lab_definition_id):
                raise RuntimeError(f"实验课时已关联其他定义，拒绝覆盖：{record['lesson_code']}")
            if extension.linked_lab_definition_id is None:
                extension.linked_lab_definition_id = data.spec.lab_definition_id
                enqueue_event(
                    session,
                    event_type="lesson.lab_definition.linked",
                    aggregate_type="lesson_resource",
                    aggregate_id=extension.lesson_resource_id,
                    actor_user_id=context.user_id,
                    idempotency_key=f"formal-lab-link-v1:{extension.lesson_resource_id}",
                    payload={
                        "course_id": COURSE_ID,
                        "lesson_id": extension.lesson_id,
                        "lab_definition_id": data.spec.lab_definition_id,
                    },
                )
                linked_count += 1
        session.commit()
        _ensure_rsa_knowledge(session)
        return {"definitions": len(records), "created": created_count, "linked": linked_count}
    finally:
        session.close()


def _ensure_templates(session) -> None:
    templates = (
        (
            "labt_crypto_dual",
            "双机密码学实验",
            "学生操作节点与目标验证节点组成的隔离环境，适合对称加密、非对称加密和哈希实验。",
            {"node_roles": ["STUDENT_WORKSTATION", "TARGET"], "network_env": "ISOLATED", "automatic_grading": True, "example_lab_definition_id": "lab_rsa"},
        ),
        (
            "labt_data_processing",
            "数据处理实验",
            "双节点数据处理环境，适合编码、脱敏、备份和日志分析。",
            {"node_roles": ["STUDENT_WORKSTATION", "TARGET"], "network_env": "ISOLATED", "automatic_grading": True, "example_lab_definition_id": "lab_base64"},
        ),
        (
            "labt_database_access",
            "数据库访问控制实验",
            "学生操作节点与 MySQL（关系型数据库）教学数据库组成的隔离权限实验环境。",
            {"node_roles": ["STUDENT_WORKSTATION", "TARGET"], "network_env": "ISOLATED", "automatic_grading": True, "example_lab_definition_id": "lab_database_rbac"},
        ),
    )
    for template_id, name, description, spec in templates:
        existing = session.get(LabTemplate, template_id)
        if existing:
            if (existing.name, existing.description, existing.spec_json) == (name, description, spec):
                continue
            previous_spec = dict(spec)
            previous_spec.pop("example_lab_definition_id")
            is_previous_system_template = (
                existing.created_by == SEED_USER_ID
                and existing.name == name
                and existing.description == description
                and existing.spec_json == previous_spec
            )
            is_legacy_crypto_template = (
                template_id == "labt_crypto_dual"
                and existing.created_by == SEED_USER_ID
                and existing.name == name
                and existing.description == "Student + Target 两台 Ubuntu，预置 OpenSSL，适合 RSA、AES 和哈希实验。"
                and existing.spec_json == previous_spec
            )
            if not (is_previous_system_template or is_legacy_crypto_template):
                raise RuntimeError(f"已有实验模板与正式 v1.0.0 内容冲突：{template_id}")
            existing.description = description
            existing.spec_json = spec
            continue
        session.add(
            LabTemplate(
                template_id=template_id,
                name=name,
                description=description,
                spec_json=spec,
                created_by=SEED_USER_ID,
                created_at=datetime.now(),
            )
        )
    session.commit()


def _ensure_rsa_knowledge(session) -> None:
    if not session.get(FileObject, "file_rsa_diagram"):
        content = DIAGRAM.read_bytes()
        session.add(
            FileObject(
                file_id="file_rsa_diagram",
                storage_provider="BUNDLED",
                bucket="lab-assets",
                object_key=DIAGRAM.name,
                original_name="RSA 数字签名讲解图.svg",
                mime_type="image/svg+xml",
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                created_by=SEED_USER_ID,
                created_at=datetime.now(),
            )
        )
        session.commit()

    knowledge = session.get(LabKnowledgePoint, "kp_rsa_signature")
    if not knowledge:
        knowledge = LabKnowledgePoint(
            knowledge_point_id="kp_rsa_signature",
            course_id=COURSE_ID,
            title="RSA 密钥对与数字签名",
            explain_text="先对原始数据计算 SHA-256 摘要，再使用私钥签名；接收方用公钥验签并比对摘要。实验判定同时检查签名文件和验签结果。",
            created_by=SEED_USER_ID,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(knowledge)
        session.flush()
        question_id = session.scalar(
            select(Question.question_id)
            .join(QuestionLessonMap, QuestionLessonMap.question_id == Question.question_id)
            .where(QuestionLessonMap.lesson_id == "lesson_lab_04", Question.status == "APPROVED")
            .order_by(Question.created_at, Question.question_id)
            .limit(1)
        )
        if question_id:
            session.add(
                LabQuestionKnowledgeMap(
                    map_id="kqm_rsa_signature_v1",
                    knowledge_point_id=knowledge.knowledge_point_id,
                    question_id=question_id,
                )
            )
        session.add(
            LabExplainDiagram(
                diagram_id="diag_rsa_signature",
                knowledge_point_id=knowledge.knowledge_point_id,
                file_id="file_rsa_diagram",
                title="RSA 数字签名流程",
                order_no=1,
            )
        )
        session.commit()


def seed_rsa() -> None:
    """Backward-compatible entry point used by the existing G3 fixture."""
    seed_formal_lab_definitions()


if __name__ == "__main__":
    seed_formal_lab_definitions()
