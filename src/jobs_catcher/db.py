from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from . import auth
from .models import Base, User


def make_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    kwargs = {"future": True, "connect_args": connect_args}
    if database_url in {"sqlite:///:memory:", "sqlite://"}:
        kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def bootstrap_admin(db: Session) -> User:
    existing = db.scalar(select(User.id).limit(1))
    if existing is not None:
        user = db.scalar(select(User).where(User.login == "admin"))
        return user if user else db.get(User, existing)
    admin = User(login="admin", password_hash=auth.hash_password("admin"), role="superuser", display_name="Admin", must_change_password=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def session_expiry(days: int = 14) -> datetime:
    return utcnow() + timedelta(days=days)
