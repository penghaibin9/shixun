import json
import hashlib
from datetime import datetime
from pathlib import Path

from app.common.context import UserContext
from app.common.models import FileObject
from .database import create_session_factory
from .models import LabDefinition, LabExplainDiagram, LabKnowledgePoint, LabQuestionKnowledgeMap, LabTemplate
from .schemas import LabCreate, LabDefinitionSpec
from .service import LabService


FIXTURE = Path(__file__).with_name("fixtures") / "rsa-v1.json"
DIAGRAM = Path(__file__).with_name("fixtures") / "rsa-signature-flow.svg"
COURSE_ID = "course_data_security"


def seed_rsa() -> None:
    session = create_session_factory()()
    context = UserContext(
        user_id="user_seed_c", role="teacher", teacher_id="teacher_seed_c", student_id=None,
        permissions=frozenset({"labs.read", "labs.write", "labs.publish", "labs.knowledge.write"}),
        course_ids=frozenset({COURSE_ID}), class_ids=frozenset({"class_netsec_2301"}),
    )
    try:
        service = LabService(session, context)
        if not session.get(LabTemplate, "labt_crypto_dual"):
            template = LabTemplate(
                template_id="labt_crypto_dual", name="双机密码学实验",
                description="Student + Target 两台 Ubuntu，预置 OpenSSL，适合 RSA、AES 和哈希实验。",
                spec_json={"node_roles": ["STUDENT_WORKSTATION", "TARGET"], "network_env": "ISOLATED", "automatic_grading": True},
                created_by=context.user_id, created_at=datetime.now(),
            )
            session.add(template)
            session.commit()
        if not session.get(LabDefinition, "lab_rsa"):
            spec = LabDefinitionSpec.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
            created = service.create_lab(LabCreate(course_id=COURSE_ID, code="EXP-RSA-001", category="密码学", objective="掌握 RSA 密钥生成、加解密、数字签名与验签流程。", spec=spec), "seed-rsa-definition-v1")
            version_id = created["latest_version"]["lab_version_id"]
            service.validate_version(version_id, "seed-rsa-validate-v1")
            service.publish_version(version_id, "seed-rsa-publish-v1")
        if not session.get(FileObject, "file_rsa_diagram"):
            content = DIAGRAM.read_bytes()
            session.add(FileObject(file_id="file_rsa_diagram", storage_provider="BUNDLED", bucket="lab-assets", object_key=DIAGRAM.name, original_name="RSA 数字签名讲解图.svg", mime_type="image/svg+xml", size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), created_by=context.user_id, created_at=datetime.now()))
            session.commit()
        # 验收和跨域引用使用冻结标识；不能因同名草稿已存在而跳过规范数据。
        knowledge = session.get(LabKnowledgePoint, "kp_rsa_signature")
        if not knowledge:
            knowledge = LabKnowledgePoint(knowledge_point_id="kp_rsa_signature", course_id=COURSE_ID, title="RSA 密钥对与数字签名", explain_text="先对原始数据计算 SHA-256 摘要，再使用私钥签名；接收方用公钥验签并比对摘要。实验判定同时检查签名文件和验签结果。", created_by=context.user_id, created_at=datetime.now(), updated_at=datetime.now())
            session.add(knowledge)
            session.flush()
            session.add_all([
                LabQuestionKnowledgeMap(map_id="kqm_rsa_006", knowledge_point_id=knowledge.knowledge_point_id, question_id="question_rsa_006"),
                LabExplainDiagram(diagram_id="diag_rsa_signature", knowledge_point_id=knowledge.knowledge_point_id, file_id="file_rsa_diagram", title="RSA 数字签名流程", order_no=1),
            ])
            session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    seed_rsa()
