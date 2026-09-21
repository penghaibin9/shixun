from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base


class LabTemplate(Base):
    __tablename__ = "lab_template"
    template_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text)
    spec_json: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class LabDefinition(Base):
    __tablename__ = "lab_definition"
    __table_args__ = (UniqueConstraint("course_id", "code", name="uq_lab_definition_course_code"), Index("ix_lab_definition_course", "course_id"))
    lab_definition_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(64))
    objective: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class LabVersion(Base):
    __tablename__ = "lab_version"
    __table_args__ = (UniqueConstraint("lab_definition_id", "version", name="uq_lab_version_number"), Index("ix_lab_version_status", "status"))
    lab_version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lab_definition_id: Mapped[str] = mapped_column(ForeignKey("lab_definition.lab_definition_id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    spec_json: Mapped[dict] = mapped_column(JSON)
    validation_errors_json: Mapped[list] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LabScene(Base):
    __tablename__ = "lab_scene"
    scene_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lab_version_id: Mapped[str] = mapped_column(ForeignKey("lab_version.lab_version_id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(128))


class LabSceneNetwork(Base):
    __tablename__ = "lab_scene_network"
    __table_args__ = (UniqueConstraint("scene_id", "network_key", name="uq_lab_network_key"),)
    network_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("lab_scene.scene_id", ondelete="CASCADE"))
    network_key: Mapped[str] = mapped_column(String(64))
    cidr_policy: Mapped[str] = mapped_column(String(64))
    internet_access: Mapped[bool] = mapped_column(Boolean)
    egress_allowlist_json: Mapped[list] = mapped_column(JSON)
    student_isolation: Mapped[bool] = mapped_column(Boolean)


class LabSceneNode(Base):
    __tablename__ = "lab_scene_node"
    __table_args__ = (UniqueConstraint("scene_id", "node_key", name="uq_lab_scene_node_key"),)
    scene_node_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("lab_scene.scene_id", ondelete="CASCADE"))
    node_key: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(64))
    network_env: Mapped[str] = mapped_column(String(16))
    network_keys_json: Mapped[list] = mapped_column(JSON)
    device_model: Mapped[str] = mapped_column(String(128))
    cpu_limit: Mapped[float] = mapped_column(Float)
    memory_mb: Mapped[int] = mapped_column(Integer)
    ip_policy: Mapped[str] = mapped_column(String(64))
    ports_json: Mapped[list] = mapped_column(JSON)
    startup_command: Mapped[str] = mapped_column(String(512))
    mounts_json: Mapped[list] = mapped_column(JSON)
    position_x: Mapped[int] = mapped_column(Integer)
    position_y: Mapped[int] = mapped_column(Integer)


class LabImageBinding(Base):
    __tablename__ = "lab_image_binding"
    __table_args__ = (UniqueConstraint("lab_version_id", "node_key", name="uq_lab_image_binding_node"), Index("ix_lab_image_digest", "image_digest"))
    image_binding_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lab_version_id: Mapped[str] = mapped_column(ForeignKey("lab_version.lab_version_id", ondelete="CASCADE"))
    node_key: Mapped[str] = mapped_column(String(64))
    infra_image_id: Mapped[str] = mapped_column(String(36))
    image_digest: Mapped[str] = mapped_column(String(71))


class LabDagNode(Base):
    __tablename__ = "lab_dag_node"
    __table_args__ = (UniqueConstraint("lab_version_id", "node_key", name="uq_lab_dag_node_key"),)
    dag_node_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lab_version_id: Mapped[str] = mapped_column(ForeignKey("lab_version.lab_version_id", ondelete="CASCADE"))
    node_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    order_no: Mapped[int] = mapped_column(Integer)


class LabDagEdge(Base):
    __tablename__ = "lab_dag_edge"
    __table_args__ = (UniqueConstraint("lab_version_id", "from_node_key", "to_node_key", name="uq_lab_dag_edge"),)
    dag_edge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lab_version_id: Mapped[str] = mapped_column(ForeignKey("lab_version.lab_version_id", ondelete="CASCADE"))
    from_node_key: Mapped[str] = mapped_column(String(64))
    to_node_key: Mapped[str] = mapped_column(String(64))


class LabCheckpoint(Base):
    __tablename__ = "lab_checkpoint"
    __table_args__ = (UniqueConstraint("lab_version_id", "checkpoint_key", name="uq_lab_checkpoint_key"), Index("ix_lab_checkpoint_judge_type", "judge_type"))
    checkpoint_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    checkpoint_key: Mapped[str] = mapped_column(String(64))
    lab_version_id: Mapped[str] = mapped_column(ForeignKey("lab_version.lab_version_id", ondelete="CASCADE"))
    dag_node_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    score: Mapped[int] = mapped_column(Integer)
    judge_type: Mapped[str] = mapped_column(String(32))
    judge_target: Mapped[str] = mapped_column(String(512))
    judge_config_json: Mapped[dict] = mapped_column(JSON)
    failure_message: Mapped[str] = mapped_column(String(512))
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    order_no: Mapped[int] = mapped_column(Integer)


class LabKnowledgePoint(Base):
    __tablename__ = "lab_knowledge_point"
    __table_args__ = (Index("ix_lab_knowledge_course", "course_id"),)
    knowledge_point_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(160))
    explain_text: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class LabQuestionKnowledgeMap(Base):
    __tablename__ = "lab_question_knowledge_map"
    __table_args__ = (UniqueConstraint("knowledge_point_id", "question_id", name="uq_lab_knowledge_question"), Index("ix_lab_question_ref", "question_id"))
    map_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    knowledge_point_id: Mapped[str] = mapped_column(ForeignKey("lab_knowledge_point.knowledge_point_id", ondelete="CASCADE"))
    question_id: Mapped[str] = mapped_column(String(36))


class LabExplainDiagram(Base):
    __tablename__ = "lab_explain_diagram"
    __table_args__ = (Index("ix_lab_diagram_file", "file_id"),)
    diagram_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    knowledge_point_id: Mapped[str] = mapped_column(ForeignKey("lab_knowledge_point.knowledge_point_id", ondelete="CASCADE"))
    file_id: Mapped[str] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(160))
    order_no: Mapped[int] = mapped_column(Integer)


class LabRelease(Base):
    __tablename__ = "lab_release"
    __table_args__ = (Index("ix_lab_release_class_status", "class_id", "status"),)
    lab_release_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lab_version_id: Mapped[str] = mapped_column(ForeignKey("lab_version.lab_version_id"))
    course_id: Mapped[str] = mapped_column(String(36))
    class_id: Mapped[str] = mapped_column(String(36))
    lesson_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LabPublishConfig(Base):
    __tablename__ = "lab_publish_config"
    publish_config_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lab_release_id: Mapped[str] = mapped_column(ForeignKey("lab_release.lab_release_id", ondelete="CASCADE"), unique=True)
    opens_at: Mapped[datetime] = mapped_column(DateTime)
    closes_at: Mapped[datetime] = mapped_column(DateTime)
    max_attempts: Mapped[int] = mapped_column(Integer)
    timeout_minutes: Mapped[int] = mapped_column(Integer)
    max_concurrency: Mapped[int] = mapped_column(Integer)
    teacher_preview_required: Mapped[bool] = mapped_column(Boolean)
    preflight_json: Mapped[dict] = mapped_column(JSON)
    preview_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
