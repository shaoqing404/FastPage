import logging

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routers import auth, chat, documents, jobs, knowledge_bases, metrics, platform, providers, skills
from app.api.routers import runtime_observations
from app.api.routers import compliance_checks, compliance_runs
from app.api.routers import workspaces, workspace_invites
from app.core.bootstrap import init_db
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode, error_envelope, status_to_error_code
from app.core.request_context import RequestIDMiddleware, get_request_id


logger = logging.getLogger("pageindex")

settings = get_settings()
app = FastAPI(title=settings.app_name)

# ── Request ID middleware (must be added before CORS so it runs first) ──────
app.add_middleware(RequestIDMiddleware)

# ── CORS ────────────────────────────────────────────────────────────────────
if settings.app_env == "prod":
    _allow_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    _allow_headers = ["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"]
else:
    _allow_methods = ["*"]
    _allow_headers = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_origin_regex=settings.cors_allow_origin_regex or None,
    allow_credentials=True,
    allow_methods=_allow_methods,
    allow_headers=_allow_headers,
)


# ── Startup ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup() -> None:
    init_db()


# ── Health check ────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return Response(content="ok", media_type="text/plain")


# ── Unified exception handlers ──────────────────────────────────────────────

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(
            code=exc.code,
            message=exc.message,
            request_id=get_request_id(),
            details=exc.details,
        ),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = status_to_error_code(exc.status_code)
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(
            code=code,
            message=message,
            request_id=get_request_id(),
        ),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_envelope(
            code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed",
            request_id=get_request_id(),
            details=exc.errors(),
        ),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception during request %s", get_request_id())
    return JSONResponse(
        status_code=500,
        content=error_envelope(
            code=ErrorCode.INTERNAL_ERROR,
            message="Internal server error",
            request_id=get_request_id(),
        ),
    )


# ── Routers ─────────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(jobs.router)
app.include_router(knowledge_bases.router)
app.include_router(compliance_checks.router)
app.include_router(compliance_runs.router)
app.include_router(skills.router)
app.include_router(chat.router)
app.include_router(providers.router)
app.include_router(runtime_observations.router)
app.include_router(metrics.router)
app.include_router(workspaces.router)
app.include_router(workspace_invites.router)
app.include_router(platform.router)
