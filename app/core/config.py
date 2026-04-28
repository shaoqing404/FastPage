import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATABASE_MODE_SQLITE = "sqlite"
DATABASE_MODE_MYSQL = "mysql"
VALID_DATABASE_MODES = frozenset({DATABASE_MODE_SQLITE, DATABASE_MODE_MYSQL})


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
    database_mode: str
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
    redis_host: str
    redis_port: int
    redis_password: str
    redis_db: int
    queue_name_parse: str
    queue_name_chat: str
    queue_name_compliance: str

    # ── Worker ──────────────────────────────────────────────────────────────
    worker_node_code: str
    worker_process_count: int
    worker_max_tasks_per_child: int
    worker_max_rss_mb: int
    worker_heartbeat_interval_seconds: int
    worker_heartbeat_ttl_seconds: int
    worker_reconnect_delay_ms: int
    worker_registry_prefix: str
    redis_socket_timeout_seconds: int
    redis_socket_connect_timeout_seconds: int
    redis_health_check_interval_seconds: int

    # ── Chat run ────────────────────────────────────────────────────────────
    chat_run_poll_interval_ms: int
    chat_run_request_timeout_seconds: int
    chat_run_lease_timeout_seconds: int
    chat_run_queue_retry_delay_ms: int
    compliance_run_poll_interval_ms: int
    compliance_run_request_timeout_seconds: int
    compliance_run_lease_timeout_seconds: int
    compliance_run_queue_retry_delay_ms: int

    # ── Retrieval / rerank / embedding ──────────────────────────────────────
    retrieval_max_concurrency: int
    retrieval_manual_gate_mode: str
    retrieval_manual_gate_chat_live_enabled: bool
    run_max_manuals: int
    run_step_max_retries: int
    run_step_retry_base_ms: int
    system_rerank_enabled: bool
    system_rerank_base_url: str
    system_rerank_api_key: str
    system_rerank_model: str
    system_rerank_provider_type: str
    system_embedding_enabled: bool
    system_embedding_base_url: str
    system_embedding_api_key: str
    system_embedding_model: str
    system_embedding_provider_type: str
    routing_node_es_enabled: bool
    routing_node_es_url: str
    routing_node_es_host: str
    routing_node_es_port: int
    routing_node_es_user: str
    routing_node_es_password: str
    routing_node_es_use_ssl: bool
    routing_node_es_index_prefix: str
    deepresearch_runtime_pdf_fallback_enabled: bool

    # ── Routing asset build hooks ───────────────────────────────────────────
    routing_route_docs_build_mode: str
    routing_synthetic_queries_build_mode: str
    routing_embeddings_build_mode: str

    # ── Runtime observability ───────────────────────────────────────────────
    observation_text_max_chars: int

    # ── Upload limits ───────────────────────────────────────────────────────
    max_upload_bytes: int

    # ── Provider outbound safety ────────────────────────────────────────────
    provider_url_allow_private_nets: bool

    # ── Bind ────────────────────────────────────────────────────────────────
    api_host: str


def _env_text(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _env_first(names: tuple[str, ...], default: str) -> str:
    for name in names:
        value = _env_text(name)
        if value is not None:
            return value
    return default


def _infer_database_mode_from_url(database_url: str) -> str:
    lowered = database_url.lower()
    if lowered.startswith("mysql"):
        return DATABASE_MODE_MYSQL
    return DATABASE_MODE_SQLITE


def _sqlite_database_url(data_dir: Path) -> str:
    sqlite_path = _env_text("SQLITE_PATH")
    path = Path(sqlite_path).expanduser() if sqlite_path else data_dir / "app.db"
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def _mysql_database_url() -> str:
    host = _env_text("MYSQL_HOST") or "127.0.0.1"
    port = _env_text("MYSQL_PORT") or "3306"
    database = _env_text("MYSQL_DATABASE")
    user = _env_text("MYSQL_USER")
    password = _env_text("MYSQL_PASSWORD")

    missing: list[str] = []
    if database is None:
        missing.append("MYSQL_DATABASE")
    if user is None:
        missing.append("MYSQL_USER")
    if password is None:
        missing.append("MYSQL_PASSWORD")
    if missing:
        raise ValueError(
            "DATABASE_MODE=mysql requires the following environment variables: "
            + ", ".join(missing)
        )

    try:
        port_number = int(port)
    except ValueError as exc:
        raise ValueError("MYSQL_PORT must be an integer") from exc

    return (
        "mysql+pymysql://"
        f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port_number}/{quote_plus(database)}"
    )


def _resolve_database_runtime(data_dir: Path) -> tuple[str, str]:
    # Priority:
    # 1. DATABASE_URL is an expert override and wins when explicitly set.
    # 2. Otherwise DATABASE_MODE decides between local SQLite and MySQL assembly.
    explicit_database_url = _env_text("DATABASE_URL")
    if explicit_database_url is not None:
        return _infer_database_mode_from_url(explicit_database_url), explicit_database_url

    database_mode = (_env_text("DATABASE_MODE") or DATABASE_MODE_SQLITE).lower()
    if database_mode not in VALID_DATABASE_MODES:
        raise ValueError(
            f"Unsupported DATABASE_MODE={database_mode!r}. "
            f"Expected one of: {', '.join(sorted(VALID_DATABASE_MODES))}."
        )

    if database_mode == DATABASE_MODE_MYSQL:
        return DATABASE_MODE_MYSQL, _mysql_database_url()
    return DATABASE_MODE_SQLITE, _sqlite_database_url(data_dir)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "dev").lower()
    if app_env not in ("dev", "test", "prod"):
        app_env = "dev"

    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    database_mode, database_url = _resolve_database_runtime(data_dir)

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

    # ── Redis URL (built from split fields; explicit REDIS_URL wins) ────────
    _explicit_redis_url = os.getenv("REDIS_URL")
    if _explicit_redis_url is not None and _explicit_redis_url.strip():
        redis_url = _explicit_redis_url.strip()
    else:
        _redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
        _redis_port = os.getenv("REDIS_PORT", "6379")
        _redis_password = os.getenv("REDIS_PASSWORD", "")
        _redis_db = os.getenv("REDIS_DB", "0")
        if _redis_password:
            redis_url = f"redis://:{quote_plus(_redis_password)}@{_redis_host}:{_redis_port}/{_redis_db}"
        else:
            redis_url = f"redis://{_redis_host}:{_redis_port}/{_redis_db}"
    redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_password = os.getenv("REDIS_PASSWORD", "")
    redis_db = int(os.getenv("REDIS_DB", "0"))

    # ── ES URL (built from split fields; explicit ROUTING_NODE_ES_URL wins) ─
    _explicit_es_url = os.getenv("ROUTING_NODE_ES_URL")
    if _explicit_es_url is not None and _explicit_es_url.strip():
        routing_node_es_url = _explicit_es_url.strip()
    else:
        _es_host = os.getenv("ROUTING_NODE_ES_HOST", "127.0.0.1")
        _es_port = os.getenv("ROUTING_NODE_ES_PORT", "9200")
        _es_user = os.getenv("ROUTING_NODE_ES_USER", "")
        _es_password = os.getenv("ROUTING_NODE_ES_PASSWORD", "")
        _es_ssl = os.getenv("ROUTING_NODE_ES_USE_SSL", "false").lower() in {"1", "true", "yes", "on"}
        _scheme = "https" if _es_ssl else "http"
        if _es_user and _es_password:
            routing_node_es_url = f"{_scheme}://{quote_plus(_es_user)}:{quote_plus(_es_password)}@{_es_host}:{_es_port}"
        else:
            routing_node_es_url = f"{_scheme}://{_es_host}:{_es_port}"
    routing_node_es_host = os.getenv("ROUTING_NODE_ES_HOST", "127.0.0.1")
    routing_node_es_port = int(os.getenv("ROUTING_NODE_ES_PORT", "9200"))
    routing_node_es_user = os.getenv("ROUTING_NODE_ES_USER", "")
    routing_node_es_password = os.getenv("ROUTING_NODE_ES_PASSWORD", "")
    routing_node_es_use_ssl = os.getenv("ROUTING_NODE_ES_USE_SSL", "false").lower() in {"1", "true", "yes", "on"}

    settings = Settings(
        app_name="PageIndex Service",
        app_env=app_env,
        admin_username=os.getenv("ADMIN_USERNAME", "admin"),
        admin_password=admin_password,
        secret_key=secret_key,
        data_dir=data_dir,
        llm_base_url=os.getenv("LLM_BASE_URL", os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")),
        llm_api_key=os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")),
        database_mode=database_mode,
        database_url=database_url,
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
        redis_url=redis_url,
        redis_host=redis_host,
        redis_port=redis_port,
        redis_password=redis_password,
        redis_db=redis_db,
        queue_name_parse=os.getenv("QUEUE_NAME_PARSE", "pageindex:parse"),
        queue_name_chat=os.getenv("QUEUE_NAME_CHAT", "pageindex:chat"),
        queue_name_compliance=os.getenv("QUEUE_NAME_COMPLIANCE", "pageindex:compliance"),
        worker_node_code=os.getenv(
            "WORKER_NODE_CODE",
            f"{os.getenv('WORKER_NODE_CODE_PREFIX', 'worker')}:{os.getenv('HOSTNAME', 'local')}",
        ),
        worker_process_count=int(os.getenv("WORKER_PROCESS_COUNT", "1")),
        worker_max_tasks_per_child=int(os.getenv("WORKER_MAX_TASKS_PER_CHILD", "50")),
        worker_max_rss_mb=int(os.getenv("WORKER_MAX_RSS_MB", "1024")),
        worker_heartbeat_interval_seconds=int(os.getenv("WORKER_HEARTBEAT_INTERVAL_SECONDS", "15")),
        worker_heartbeat_ttl_seconds=int(os.getenv("WORKER_HEARTBEAT_TTL_SECONDS", "45")),
        worker_reconnect_delay_ms=int(os.getenv("WORKER_RECONNECT_DELAY_MS", "2000")),
        worker_registry_prefix=os.getenv("WORKER_REGISTRY_PREFIX", "pageindex:workers"),
        redis_socket_timeout_seconds=int(os.getenv("REDIS_SOCKET_TIMEOUT_SECONDS", "30")),
        redis_socket_connect_timeout_seconds=int(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", "5")),
        redis_health_check_interval_seconds=int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL_SECONDS", "30")),
        chat_run_poll_interval_ms=int(os.getenv("CHAT_RUN_POLL_INTERVAL_MS", "200")),
        chat_run_request_timeout_seconds=int(os.getenv("CHAT_RUN_REQUEST_TIMEOUT_SECONDS", "30")),
        chat_run_lease_timeout_seconds=int(os.getenv("CHAT_RUN_LEASE_TIMEOUT_SECONDS", "90")),
        chat_run_queue_retry_delay_ms=int(os.getenv("CHAT_RUN_QUEUE_RETRY_DELAY_MS", "500")),
        compliance_run_poll_interval_ms=int(os.getenv("COMPLIANCE_RUN_POLL_INTERVAL_MS", "500")),
        compliance_run_request_timeout_seconds=int(os.getenv("COMPLIANCE_RUN_REQUEST_TIMEOUT_SECONDS", "30")),
        compliance_run_lease_timeout_seconds=int(os.getenv("COMPLIANCE_RUN_LEASE_TIMEOUT_SECONDS", "120")),
        compliance_run_queue_retry_delay_ms=int(os.getenv("COMPLIANCE_RUN_QUEUE_RETRY_DELAY_MS", "500")),
        retrieval_max_concurrency=int(os.getenv("RETRIEVAL_MAX_CONCURRENCY", "8")),
        retrieval_manual_gate_mode=_env_first(
            ("RETRIEVAL_MANUAL_GATE_MODE",),
            "off",
        ),
        retrieval_manual_gate_chat_live_enabled=(
            os.getenv("RETRIEVAL_MANUAL_GATE_CHAT_LIVE_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
        ),
        run_max_manuals=int(os.getenv("RUN_MAX_MANUALS", "20")),
        run_step_max_retries=int(os.getenv("RUN_STEP_MAX_RETRIES", "2")),
        run_step_retry_base_ms=int(os.getenv("RUN_STEP_RETRY_BASE_MS", "500")),
        system_rerank_enabled=os.getenv("SYSTEM_RERANK_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
        system_rerank_base_url=os.getenv("SYSTEM_RERANK_BASE_URL", ""),
        system_rerank_api_key=os.getenv("SYSTEM_RERANK_API_KEY", ""),
        system_rerank_model=os.getenv("SYSTEM_RERANK_MODEL", ""),
        system_rerank_provider_type=os.getenv("SYSTEM_RERANK_PROVIDER_TYPE", "openai_compatible"),
        system_embedding_enabled=os.getenv("SYSTEM_EMBEDDING_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
        system_embedding_base_url=os.getenv("SYSTEM_EMBEDDING_BASE_URL", ""),
        system_embedding_api_key=os.getenv("SYSTEM_EMBEDDING_API_KEY", ""),
        system_embedding_model=os.getenv("SYSTEM_EMBEDDING_MODEL", ""),
        system_embedding_provider_type=os.getenv("SYSTEM_EMBEDDING_PROVIDER_TYPE", "openai_compatible"),
        routing_node_es_enabled=os.getenv("ROUTING_NODE_ES_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
        routing_node_es_url=routing_node_es_url,
        routing_node_es_host=routing_node_es_host,
        routing_node_es_port=routing_node_es_port,
        routing_node_es_user=routing_node_es_user,
        routing_node_es_password=routing_node_es_password,
        routing_node_es_use_ssl=routing_node_es_use_ssl,
        routing_node_es_index_prefix=os.getenv("ROUTING_NODE_ES_INDEX_PREFIX", "pageindex-node-embeddings"),
        deepresearch_runtime_pdf_fallback_enabled=(
            os.getenv("DEEPRESEARCH_RUNTIME_PDF_FALLBACK_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
        ),
        routing_route_docs_build_mode=_env_first(
            ("ROUTING_ROUTE_DOCS_BUILD_MODE", "ROUTING_ROUTE_DOC_BUILD_MODE"),
            "disabled",
        ),
        routing_synthetic_queries_build_mode=_env_first(
            ("ROUTING_SYNTHETIC_QUERIES_BUILD_MODE",),
            "disabled",
        ),
        routing_embeddings_build_mode=_env_first(
            ("ROUTING_EMBEDDINGS_BUILD_MODE",),
            "disabled",
        ),
        observation_text_max_chars=int(os.getenv("OBSERVATION_TEXT_MAX_CHARS", "12000")),
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
