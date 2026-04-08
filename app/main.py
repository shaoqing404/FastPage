from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, chat, documents, jobs, metrics, providers, skills
from app.core.bootstrap import init_db
from app.core.config import get_settings


settings = get_settings()
app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_origin_regex=settings.cors_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/healthz")
def healthz():
    return Response(content="ok", media_type="text/plain")


app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(jobs.router)
app.include_router(skills.router)
app.include_router(chat.router)
app.include_router(providers.router)
app.include_router(metrics.router)
