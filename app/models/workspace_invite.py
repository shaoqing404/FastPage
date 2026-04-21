from datetime import datetime

from sqlalchemy import Computed, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.db import Base


def _normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("Workspace invite email cannot be empty")
    return normalized


class WorkspaceInvite(Base):
    __tablename__ = "workspace_invites"
    __table_args__ = (
        Index("ix_workspace_invites_workspace_email_status", "workspace_id", "email", "status"),
        Index(
            "uq_workspace_invites_workspace_pending_normalized_email",
            "workspace_id",
            "pending_normalized_email",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    permissions_override_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    pending_normalized_email: Mapped[str | None] = mapped_column(
        String(255),
        Computed(
            "CASE WHEN status = 'pending' THEN lower(trim(email)) ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
    invited_by: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    accepted_user_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id"), nullable=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    @validates("email")
    def _normalize_email_on_write(self, _key: str, value: str) -> str:
        return _normalize_email(value)
