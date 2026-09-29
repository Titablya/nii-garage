from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .settings import DatabaseSettings


@dataclass(slots=True)
class Database:
    engine: Engine
    session_factory: sessionmaker[Session]

    def session(self) -> Generator[Session, None, None]:
        """Yield a transactional session suitable for a FastAPI dependency later."""
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def create_database(settings: DatabaseSettings | None = None) -> Database:
    settings = settings or DatabaseSettings.from_env()
    connect_args: dict[str, bool] = {}
    if settings.url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(settings.url, echo=settings.echo, connect_args=connect_args)
    return Database(engine=engine, session_factory=sessionmaker(bind=engine, expire_on_commit=False))
