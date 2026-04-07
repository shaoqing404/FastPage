from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import ChatSkill, User
from app.schemas.skills import ChatSkillCreate, ChatSkillOut, ChatSkillUpdate
from app.services.skill_service import create_skill, delete_skill as delete_skill_with_cleanup, get_skill_or_404, serialize_skill, update_skill


router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


@router.post("", response_model=ChatSkillOut)
def create_skill_endpoint(payload: ChatSkillCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    skill = create_skill(db, current_user, payload)
    return serialize_skill(skill)


@router.get("", response_model=list[ChatSkillOut])
def list_skills(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    skills = db.scalars(
        select(ChatSkill).where(ChatSkill.tenant_id == current_user.tenant_id).options(selectinload(ChatSkill.documents))
    ).all()
    return [serialize_skill(skill) for skill in skills]


@router.get("/{skill_id}", response_model=ChatSkillOut)
def get_skill(skill_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    skill = get_skill_or_404(db, current_user, skill_id)
    return serialize_skill(skill)


@router.patch("/{skill_id}", response_model=ChatSkillOut)
def patch_skill(skill_id: str, payload: ChatSkillUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    skill = update_skill(db, current_user, skill_id, payload)
    return serialize_skill(skill)


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Response:
    delete_skill_with_cleanup(db, current_user, skill_id)
    return Response(status_code=204)
