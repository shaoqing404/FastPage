from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine_kwargs = {
    "future": True,
    "connect_args": connect_args,
}
if not settings.database_url.startswith("sqlite"):
    # Pool budget: total <= process_count * (pool_size + max_overflow) + scripts/admin.
    # Current load-test baseline: (2 API + 10 workers) * (3 + 2) = 60 app DB connections.
    engine_kwargs.update(
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
engine = create_engine(settings.database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
