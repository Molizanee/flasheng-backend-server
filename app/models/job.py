import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base


class ResumeJob(Base):
    __tablename__ = "resume_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    # pending -> processing -> completed | failed

    # Owner (Supabase user id from JWT)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Input data
    github_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linkedin_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Intermediate data (stored for debugging / re-generation)
    github_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    linkedin_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_generated_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Output URLs
    html_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Error tracking
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
