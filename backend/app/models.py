import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, Date, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="authorized_user", nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    cases: Mapped[list["MissingPersonCase"]] = relationship(back_populates="created_by")
    audit_records: Mapped[list["AuditRecord"]] = relationship(back_populates="user")


class MissingPersonCase(TimestampMixin, Base):
    __tablename__ = "missing_person_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    last_seen_location: Mapped[str | None] = mapped_column(String(255))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[User] = relationship(back_populates="cases")
    reference_images: Mapped[list["ReferenceImage"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    sightings: Mapped[list["Sighting"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    search_jobs: Mapped[list["SearchJob"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class ReferenceImage(TimestampMixin, Base):
    __tablename__ = "reference_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missing_person_cases.id"), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)

    case: Mapped[MissingPersonCase] = relationship(back_populates="reference_images")


class Sighting(TimestampMixin, Base):
    __tablename__ = "sightings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missing_person_cases.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="portal", nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="pending_review", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[str | None] = mapped_column(String(255))

    case: Mapped[MissingPersonCase] = relationship(back_populates="sightings")


class SearchJob(TimestampMixin, Base):
    __tablename__ = "search_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("missing_person_cases.id"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)

    case: Mapped[MissingPersonCase] = relationship(back_populates="search_jobs")
    candidate_matches: Mapped[list["CandidateMatch"]] = relationship(
        back_populates="search_job", cascade="all, delete-orphan"
    )


class CandidateMatch(TimestampMixin, Base):
    __tablename__ = "candidate_matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("search_jobs.id"), nullable=False)
    candidate_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="unreviewed", nullable=False)

    search_job: Mapped[SearchJob] = relationship(back_populates="candidate_matches")


class AuditRecord(TimestampMixin, Base):
    __tablename__ = "audit_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    user: Mapped[User | None] = relationship(back_populates="audit_records")
