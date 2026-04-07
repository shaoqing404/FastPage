from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import create_access_token, generate_api_key_value, get_api_key_prefix, revoke_token
from app.core.db import get_db
from app.models import ApiKey, User
from app.api.deps import get_current_principal, get_current_user
from app.core.principal import Principal
from app.schemas.auth import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeyOut, LoginRequest, TokenResponse, UserOut
from app.core.auth import bearer_scheme, verify_login


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = verify_login(db, payload.username, payload.password)
    if user is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user)
    return TokenResponse(
        access_token=token,
        user=UserOut(id=user.id, tenant_id=user.tenant_id, username=user.username),
    )


@router.post("/logout", status_code=204)
def logout(
    current_user: User = Depends(get_current_user),
    credentials=Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Response:
    _ = current_user
    if credentials is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    revoke_token(db, credentials.credentials)
    return Response(status_code=204)


@router.post("/apikeys", response_model=ApiKeyCreateResponse)
def create_api_key(
    payload: ApiKeyCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    raw_key, hashed_key = generate_api_key_value()
    api_key = ApiKey(
        id=str(uuid.uuid4()),
        tenant_id=principal.tenant_id,
        name=payload.name,
        key_prefix=get_api_key_prefix(raw_key),
        key_hash=hashed_key,
        status="active",
        created_by=principal.user_id,
        created_at=datetime.utcnow(),
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return ApiKeyCreateResponse(
        id=api_key.id,
        tenant_id=api_key.tenant_id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        status=api_key.status,
        created_at=api_key.created_at,
        api_key=raw_key,
    )


@router.get("/apikeys", response_model=list[ApiKeyOut])
def list_api_keys(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    keys = db.scalars(
        select(ApiKey).where(ApiKey.tenant_id == principal.tenant_id).order_by(ApiKey.created_at.desc())
    ).all()
    return keys


@router.delete("/apikeys/{key_id}", status_code=204)
def revoke_api_key_endpoint(
    key_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    api_key = db.get(ApiKey, key_id)
    if api_key is None or api_key.tenant_id != principal.tenant_id:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    api_key.status = "revoked"
    api_key.revoked_at = datetime.utcnow()
    db.commit()
    return Response(status_code=204)
