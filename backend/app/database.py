from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base

logger = logging.getLogger(__name__)

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None
db_backend: str = "uninitialized"


def _sqlite_connect(dbapi_connection, _connection_record) -> None:
    # Hand transactions to SQLAlchemy so concurrent bookings take a write
    # lock up front instead of deadlocking on a later upgrade.
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def _sqlite_begin(conn) -> None:
    conn.exec_driver_sql("BEGIN IMMEDIATE")


def configure_sqlite(eng: Engine) -> None:
    event.listen(eng, "connect", _sqlite_connect)
    event.listen(eng, "begin", _sqlite_begin)


def normalize_database_url(url: str) -> str:
    cleaned = url.strip()
    if cleaned.startswith("postgres://"):
        cleaned = "postgresql+psycopg://" + cleaned[len("postgres://") :]
    elif cleaned.startswith("postgresql://"):
        cleaned = "postgresql+psycopg://" + cleaned[len("postgresql://") :]
    if "neon.tech" in cleaned and "sslmode=" not in cleaned:
        cleaned += "&sslmode=require" if "?" in cleaned else "?sslmode=require"
    return cleaned


def _try_postgres(url: str) -> Engine:
    eng = create_engine(
        normalize_database_url(url),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
        future=True,
        connect_args={"connect_timeout": 15},
    )
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    return eng


def _sqlite_engine(url: str) -> Engine:
    eng = create_engine(
        url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        future=True,
    )
    configure_sqlite(eng)
    return eng


def init_engine() -> tuple[Engine, str]:
    settings = get_settings()
    if settings.database_url.strip():
        try:
            eng = _try_postgres(settings.database_url)
            logger.info("Connected to PostgreSQL")
            return eng, "postgresql"
        except SQLAlchemyError as exc:
            if settings.public_demo:
                logger.error("PostgreSQL is required for the public demo (%s)", exc)
                raise
            logger.warning("PostgreSQL unavailable (%s); falling back to SQLite", exc)
    else:
        logger.info("DATABASE_URL is empty; using SQLite")
    return _sqlite_engine(settings.sqlite_url), "sqlite"


def _schema_is_legacy(eng: Engine) -> bool:
    insp = inspect(eng)
    if not insp.has_table("appointments"):
        return False
    columns = {column["name"] for column in insp.get_columns("appointments")}
    return "desk_id" not in columns


def init_db() -> None:
    global engine, SessionLocal, db_backend
    engine, db_backend = init_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    if _schema_is_legacy(engine):
        logger.warning("Resetting clinic tables so each tester gets a separate board")
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        raise RuntimeError("Database is not initialized")
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
