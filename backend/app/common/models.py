from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FileObject(Base):
    __tablename__ = "file_object"
    __table_args__ = (UniqueConstraint("storage_provider", "bucket", "object_key", name="uq_file_object_location"), UniqueConstraint("sha256", "size_bytes", name="uq_file_object_content"))
    file_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    storage_provider: Mapped[str] = mapped_column(String(32))
    bucket: Mapped[str] = mapped_column(String(128))
    object_key: Mapped[str] = mapped_column(String(512))
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class DomainEventOutbox(Base):
    __tablename__ = "domain_event_outbox"
    __table_args__ = (
        UniqueConstraint(
            "event_type",
            "idempotency_key",
            name="uq_outbox_event_idempotency",
        ),
        Index("ix_outbox_unpublished", "published_at", "occurred_at"),
    )
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128))
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[str] = mapped_column(String(36))
    actor_user_id: Mapped[str] = mapped_column(String(36))
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    payload_json: Mapped[dict] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# Import domain models so Alembic and tests see the complete metadata graph.
from app.resources import models as resource_models  # noqa: E402,F401
from app.grading import models as grading_models  # noqa: E402,F401
from app.auth import models as auth_models  # noqa: E402,F401
