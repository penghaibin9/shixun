from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.models import Base


class InfraNode(Base):
    __tablename__ = "infra_node"
    __table_args__ = (Index("ix_infra_node_schedulable", "status", "scheduling_paused"),)
    node_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(96), unique=True)
    agent_url: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24))
    scheduling_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    weight: Mapped[int] = mapped_column(Integer, default=100)
    labels_json: Mapped[dict] = mapped_column(JSON)
    cpu_total: Mapped[float] = mapped_column(Float)
    memory_total_mb: Mapped[int] = mapped_column(Integer)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class InfraNodeHeartbeat(Base):
    __tablename__ = "infra_node_heartbeat"
    __table_args__ = (Index("ix_heartbeat_node_time", "node_id", "observed_at"),)
    heartbeat_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("infra_node.node_id", name="fk_infra_node_heartbeat_node", ondelete="CASCADE")
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    cpu_available: Mapped[float] = mapped_column(Float)
    memory_available_mb: Mapped[int] = mapped_column(Integer)
    running_groups: Mapped[int] = mapped_column(Integer)
    image_digests_json: Mapped[list] = mapped_column(JSON)
    detail_json: Mapped[dict] = mapped_column(JSON)
    node = relationship("InfraNode")


class InfraImage(Base):
    __tablename__ = "infra_image"
    __table_args__ = (UniqueConstraint("digest", name="uq_infra_image_digest"), Index("ix_infra_image_enabled", "enabled"))
    image_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    tag: Mapped[str] = mapped_column(String(96))
    digest: Mapped[str] = mapped_column(String(71))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    scan_status: Mapped[str] = mapped_column(String(24))
    startup_check_status: Mapped[str] = mapped_column(String(24))
    teaching_validation_status: Mapped[str] = mapped_column(String(24))
    enabled: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class InfraImageValidation(Base):
    __tablename__ = "infra_image_validation"
    __table_args__ = (Index("ix_image_validation_image_time", "image_id", "validated_at"),)
    validation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("infra_image.image_id", name="fk_infra_image_validation_image", ondelete="CASCADE")
    )
    validation_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))
    detail_json: Mapped[dict] = mapped_column(JSON)
    validated_at: Mapped[datetime] = mapped_column(DateTime)
    image = relationship("InfraImage")


class RuntimeRequest(Base):
    __tablename__ = "runtime_request"
    __table_args__ = (
        UniqueConstraint("requested_by", "idempotency_key", name="uq_runtime_request_actor_key"),
        Index("ix_runtime_request_subject", "student_id", "created_at"),
        Index("ix_runtime_request_status", "status"),
    )
    runtime_request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lab_release_id: Mapped[str] = mapped_column(String(36))
    lab_version_id: Mapped[str] = mapped_column(String(36))
    course_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    class_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    student_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    mode: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
    requested_by: Mapped[str] = mapped_column(String(36))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    spec_snapshot_json: Mapped[dict] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    submission_status: Mapped[str] = mapped_column(String(24), default="DRAFT")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class RuntimeReleaseReadModel(Base):
    __tablename__ = "runtime_release_read_model"
    __table_args__ = (Index("ix_runtime_release_class_status", "class_id", "status"),)
    lab_release_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lab_version_id: Mapped[str] = mapped_column(String(36))
    course_id: Mapped[str] = mapped_column(String(36))
    class_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(24))
    spec_snapshot_json: Mapped[dict] = mapped_column(JSON)
    published_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class RuntimeQueue(Base):
    __tablename__ = "runtime_queue"
    __table_args__ = (UniqueConstraint("runtime_request_id", name="uq_runtime_queue_request"), Index("ix_runtime_queue_state_priority", "status", "priority", "enqueued_at"))
    queue_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    runtime_request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runtime_request.runtime_request_id", name="fk_runtime_queue_request", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(24))
    priority: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer)
    not_before: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime)
    request = relationship("RuntimeRequest")


class RuntimeInstanceGroup(Base):
    __tablename__ = "runtime_instance_group"
    __table_args__ = (
        UniqueConstraint("runtime_request_id", name="uq_runtime_group_request"),
        Index("ix_runtime_group_status", "status"),
        Index("ix_runtime_group_node_status", "node_id", "status", "scheduled_at"),
    )
    runtime_group_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    runtime_request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runtime_request.runtime_request_id", name="fk_runtime_group_request", ondelete="CASCADE")
    )
    node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("infra_node.node_id", name="fk_runtime_group_node", ondelete="RESTRICT")
    )
    provider_group_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    scheduler_score: Mapped[float] = mapped_column(Float)
    scheduler_reason: Mapped[str] = mapped_column(String(512))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    destroyed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    request = relationship("RuntimeRequest")
    node = relationship("InfraNode")


class RuntimeInstance(Base):
    __tablename__ = "runtime_instance"
    __table_args__ = (
        UniqueConstraint("runtime_group_id", "node_key", name="uq_runtime_instance_group_node"),
        Index("ix_runtime_instance_student_status", "student_id", "status"),
        Index("ix_runtime_instance_group", "runtime_group_id"),
    )
    runtime_instance_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    runtime_group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runtime_instance_group.runtime_group_id", name="fk_runtime_instance_group", ondelete="CASCADE")
    )
    student_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    node_key: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    group = relationship("RuntimeInstanceGroup")


class RuntimeContainer(Base):
    __tablename__ = "runtime_container"
    __table_args__ = (
        UniqueConstraint("provider_container_id", name="uq_runtime_provider_container"),
        UniqueConstraint("runtime_instance_id", name="uq_runtime_container_instance"),
        Index("ix_runtime_container_instance", "runtime_instance_id"),
    )
    runtime_container_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    runtime_instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runtime_instance.runtime_instance_id", name="fk_runtime_container_instance", ondelete="CASCADE")
    )
    provider_container_id: Mapped[str] = mapped_column(String(128))
    image_digest: Mapped[str] = mapped_column(String(71))
    status: Mapped[str] = mapped_column(String(24))
    metadata_json: Mapped[dict] = mapped_column(JSON)
    instance = relationship("RuntimeInstance")


class RuntimeNetwork(Base):
    __tablename__ = "runtime_network"
    __table_args__ = (
        UniqueConstraint("runtime_group_id", "network_key", name="uq_runtime_network_key"),
        UniqueConstraint("provider_network_id", name="uq_runtime_provider_network"),
    )
    runtime_network_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    runtime_group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runtime_instance_group.runtime_group_id", name="fk_runtime_network_group", ondelete="CASCADE")
    )
    network_key: Mapped[str] = mapped_column(String(64))
    provider_network_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24))
    isolation_checks_json: Mapped[dict] = mapped_column(JSON)
    group = relationship("RuntimeInstanceGroup")


class RuntimeEvent(Base):
    __tablename__ = "runtime_event"
    __table_args__ = (
        Index("ix_runtime_event_instance_time", "runtime_instance_id", "occurred_at"),
        Index("ix_runtime_event_group_time", "runtime_group_id", "occurred_at"),
    )
    runtime_event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    runtime_instance_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("runtime_instance.runtime_instance_id", name="fk_runtime_event_instance", ondelete="SET NULL"),
        nullable=True,
    )
    runtime_group_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("runtime_instance_group.runtime_group_id", name="fk_runtime_event_group", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64))
    actor_user_id: Mapped[str] = mapped_column(String(36))
    detail_json: Mapped[dict] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    instance = relationship("RuntimeInstance", foreign_keys=[runtime_instance_id])
    group = relationship("RuntimeInstanceGroup", foreign_keys=[runtime_group_id])


class RuntimeResourceUsage(Base):
    __tablename__ = "runtime_resource_usage"
    __table_args__ = (Index("ix_runtime_usage_instance_time", "runtime_instance_id", "observed_at"),)
    usage_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    runtime_instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runtime_instance.runtime_instance_id", name="fk_runtime_usage_instance", ondelete="CASCADE")
    )
    cpu_percent: Mapped[float] = mapped_column(Float)
    memory_used_mb: Mapped[int] = mapped_column(Integer)
    network_rx_bytes: Mapped[int] = mapped_column(BigInteger)
    network_tx_bytes: Mapped[int] = mapped_column(BigInteger)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    instance = relationship("RuntimeInstance")


class RuntimeTerminalSession(Base):
    __tablename__ = "runtime_terminal_session"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_terminal_token_hash"), Index("ix_terminal_instance_expiry", "runtime_instance_id", "expires_at"))
    terminal_session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    runtime_instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runtime_instance.runtime_instance_id", name="fk_runtime_terminal_instance", ondelete="CASCADE")
    )
    user_id: Mapped[str] = mapped_column(String(36))
    token_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    instance = relationship("RuntimeInstance")


class RuntimeArtifact(Base):
    __tablename__ = "runtime_artifact"
    __table_args__ = (Index("ix_runtime_artifact_instance_type", "runtime_instance_id", "artifact_type"),)
    runtime_artifact_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    runtime_instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runtime_instance.runtime_instance_id", name="fk_runtime_artifact_instance", ondelete="RESTRICT")
    )
    student_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    artifact_type: Mapped[str] = mapped_column(String(32))
    file_id: Mapped[str] = mapped_column(String(36))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    capture_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    capture_ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    instance = relationship("RuntimeInstance")


class CheckpointResult(Base):
    __tablename__ = "checkpoint_result"
    __table_args__ = (
        UniqueConstraint("runtime_instance_id", "checkpoint_id", "attempt", name="uq_checkpoint_result_attempt"),
        Index("ix_checkpoint_result_student", "student_id", "judged_at"),
    )
    checkpoint_result_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    runtime_instance_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runtime_instance.runtime_instance_id", name="fk_checkpoint_result_instance", ondelete="RESTRICT")
    )
    student_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    checkpoint_id: Mapped[str] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    score_awarded: Mapped[int] = mapped_column(Integer)
    max_score: Mapped[int] = mapped_column(Integer)
    evidence_json: Mapped[dict] = mapped_column(JSON)
    message: Mapped[str] = mapped_column(String(512))
    judged_at: Mapped[datetime] = mapped_column(DateTime)
    instance = relationship("RuntimeInstance")
