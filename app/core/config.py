import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass
class Settings:
    # ── Core ────────────────────────────────────────────────────────────────
    app_name: str
    app_env: str                       # dev | test | prod
    admin_username: str
    admin_password: str
    secret_key: str
    data_dir: Path

    # ── LLM ─────────────────────────────────────────────────────────────────
    llm_base_url: str
    llm_api_key: str

    # ── Database ────────────────────────────────────────────────────────────
    database_url: str

    # ── CORS ────────────────────────────────────────────────────────────────
    cors_allow_origins: list[str]
    cors_allow_origin_regex: str

    # ── Storage ─────────────────────────────────────────────────────────────
    storage_backend: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_prefix_path: str
    minio_secure: bool

    # ── Task queue ──────────────────────────────────────────────────────────
    task_queue_backend: str
    redis_url: str
    queue_name_parse: str
    queue_name_chat: str

    # ── Worker ──────────────────────────────────────────────────────────────
    worker_node_code: str

    # ── Chat run ────────────────────────────────────────────────────────────
    chat_run_poll_interval_ms: int
    chat_run_request_timeout_seconds: int
    chat_run_lease_timeout_seconds: int
    chat_run_queue_retry_delay_ms: int

    # ── Upload limits ───────────────────────────────────────────────────────
    max_upload_bytes: int

    # ── Provider outbound safety ────────────────────────────────────────────
    provider_url_allow_private_nets: bool

    # ── Bind ────────────────────────────────────────────────────────────────
    api_host: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "dev").lower()
    if app_env not in ("dev", "test", "prod"):
        app_env = "dev"

    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    # ── CORS defaults ──────────────────────────────────────────────────────
    _dev_origins = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174"
    )
    cors_allow_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ALLOW_ORIGINS", _dev_origins).split(",")
        if origin.strip()
    ]

    if app_env == "prod":
        # In prod, regex defaults to empty (disabled) unless explicitly set.
        cors_regex_default = ""
    else:
        # Dev/test: allow localhost only — no 0.0.0.0
        cors_regex_default = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    cors_allow_origin_regex = os.getenv("CORS_ALLOW_ORIGIN_REGEX", cors_regex_default)

    # ── Secrets ─────────────────────────────────────────────────────────────
    secret_key = os.getenv("SECRET_KEY", "pageindex-dev-secret-change-me")
    admin_password = os.getenv("ADMIN_PASSWORD", "changeme")

    # Prod startup guard — fail early if insecure defaults are used.
    if app_env == "prod":
        _insecure_secrets: list[str] = []
        if secret_key == "pageindex-dev-secret-change-me":
            _insecure_secrets.append("SECRET_KEY")
        if admin_password == "changeme":
            _insecure_secrets.append("ADMIN_PASSWORD")
        if _insecure_secrets:
            print(
                f"FATAL: Refusing to start in APP_ENV=prod with insecure defaults for: "
                f"{', '.join(_insecure_secrets)}.  Set strong values before deploying.",
                file=sys.stderr,
            )
            sys.exit(1)

    # ── Provider safety ─────────────────────────────────────────────────────
    _private_default = "true" if app_env != "prod" else "false"
    provider_url_allow_private = os.getenv(
        "PROVIDER_URL_ALLOW_PRIVATE_NETS", _private_default
    ).lower() in {"1", "true", "yes", "on"}

    settings = Settings(
        app_name="PageIndex Service",
        app_env=app_env,
        admin_username=os.getenv("ADMIN_USERNAME", "admin"),
        admin_password=admin_password,
        secret_key=secret_key,
        data_dir=data_dir,
        llm_base_url=os.getenv("LLM_BASE_URL", os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")),
        llm_api_key=os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")),
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{data_dir / 'app.db'}"),
        cors_allow_origins=cors_allow_origins,
        cors_allow_origin_regex=cors_allow_origin_regex,
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
        chat_run_poll_interval_ms=int(os.getenv("CHAT_RUN_POLL_INTERVAL_MS", "200")),
        chat_run_request_timeout_seconds=int(os.getenv("CHAT_RUN_REQUEST_TIMEOUT_SECONDS", "30")),
        chat_run_lease_timeout_seconds=int(os.getenv("CHAT_RUN_LEASE_TIMEOUT_SECONDS", "90")),
        chat_run_queue_retry_delay_ms=int(os.getenv("CHAT_RUN_QUEUE_RETRY_DELAY_MS", "500")),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", "2147483648")),  # 2 GB
        provider_url_allow_private_nets=provider_url_allow_private,
        api_host=os.getenv("API_HOST", "127.0.0.1"),
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
