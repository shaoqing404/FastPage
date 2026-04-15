from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.principal import Principal
from app.models import Workspace


def is_default_workspace(db: Session, tenant_id: str, workspace_id: str) -> bool:
    return db.scalar(
        select(Workspace.id).where(
            Workspace.tenant_id == tenant_id,
            Workspace.id == workspace_id,
            Workspace.is_default.is_(True),
        ).limit(1)
    ) is not None


def get_workspace_visibility_filter(db: Session, principal: Principal, model_class: type):
    if is_default_workspace(db, principal.tenant_id, principal.workspace_id):
        return or_(model_class.workspace_id == principal.workspace_id, model_class.workspace_id.is_(None))
    return model_class.workspace_id == principal.workspace_id
