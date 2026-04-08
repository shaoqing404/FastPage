import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass
class Settings:
    app_name: str
    admin_username: str
    admin_password: str
    secret_key: str
    data_dir: Path
    llm_base_url: str
    llm_api_key: str
    database_url: str
    cors_allow_origins: list[str]
    cors_allow_origin_regex: str
    storage_backend: str
    task_queue_backend: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_prefix_path: str
    minio_secure: bool
    redis_url: str
    queue_name_parse: str
    queue_name_chat: str
    worker_node_code: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    cors_allow_origins = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOW_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://0.0.0.0:5173,http://0.0.0.0:5174",
        ).split(",")
        if origin.strip()
    ]

    settings = Settings(
        app_name="PageIndex Service",
        admin_username=os.getenv("ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("ADMIN_PASSWORD", "changeme"),
        secret_key=os.getenv("SECRET_KEY", "pageindex-dev-secret-change-me"),
        data_dir=data_dir,
        llm_base_url=os.getenv("LLM_BASE_URL", os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")),
        llm_api_key=os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")),
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{data_dir / 'app.db'}"),
        cors_allow_origins=cors_allow_origins,
        cors_allow_origin_regex=os.getenv(
            "CORS_ALLOW_ORIGIN_REGEX",
            r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|10\.108\.\d+\.\d+)(:\d+)?$",
        ),
        storage_backend=os.getenv("STORAGE_BACKEND", "local"),
        task_queue_backend=os.getenv("TASK_QUEUE_BACKEND", "local"),
        minio_endpoint=os.getenv("MINIO_ENDPOINT", ""),
        minio_access_key=os.getenv("MINIO_ACCESS_KEY", ""),
        minio_secret_key=os.getenv("MINIO_SECRET_KEY", ""),
        minio_bucket=os.getenv("MINIO_BUCKET", ""),
        minio_prefix_path=os.getenv("MINIO_PREFIX_PATH", ""),
        minio_secure=os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes", "on"},
        redis_url=os.getenv("REDIS_URL", ""),
        queue_name_parse=os.getenv("QUEUE_NAME_PARSE", "pageindex:parse"),
        queue_name_chat=os.getenv("QUEUE_NAME_CHAT", "pageindex:chat"),
        worker_node_code=os.getenv(
            "WORKER_NODE_CODE",
            f"{os.getenv('WORKER_NODE_CODE_PREFIX', 'worker')}:{os.getenv('HOSTNAME', 'local')}",
        ),
    )

    if settings.llm_base_url:
        os.environ["OPENAI_API_BASE"] = settings.llm_base_url
    if settings.llm_api_key:
        os.environ["OPENAI_API_KEY"] = settings.llm_api_key

    return settings


def default_llm_model() -> str:
    settings = get_settings()
    if "dashscope" in settings.llm_base_url.lower():
        return "openai/qwen-plus"
    return "gpt-4o-2024-11-20"
