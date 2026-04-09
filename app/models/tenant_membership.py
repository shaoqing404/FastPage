from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_by: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
