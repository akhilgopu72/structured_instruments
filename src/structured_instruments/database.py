from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from structured_instruments.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, echo=False)
SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    return SessionLocal()


def init_db() -> None:
    import structured_instruments.models  # noqa: F401

    Base.metadata.create_all(engine)
