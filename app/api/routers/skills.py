from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal
from app.core.db import get_db
from app.core.principal import Principal
from app.schemas.skills import ChatSkillCreate, ChatSkillOut, ChatSkillUpdate
from app.services.skill_service import (
    create_skill,
    delete_skill as delete_skill_with_cleanup,
    get_skill_or_404,
    list_skills as list_skills_for_principal,
    serialize_skill,
    update_skill,
)


router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


@router.post("", response_model=ChatSkillOut)
def create_skill_endpoint(payload: ChatSkillCreate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    skill = create_skill(db, principal, payload)
    return serialize_skill(skill)


@router.get("", response_model=list[ChatSkillOut])
def list_skills(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    return [serialize_skill(skill) for skill in list_skills_for_principal(db, principal)]


@router.get("/{skill_id}", response_model=ChatSkillOut)
def get_skill(skill_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    skill = get_skill_or_404(db, principal, skill_id)
    return serialize_skill(skill)


@router.patch("/{skill_id}", response_model=ChatSkillOut)
def patch_skill(skill_id: str, payload: ChatSkillUpdate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    skill = update_skill(db, principal, skill_id, payload)
    return serialize_skill(skill)


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)) -> Response:
    delete_skill_with_cleanup(db, principal, skill_id)
    return Response(status_code=204)
