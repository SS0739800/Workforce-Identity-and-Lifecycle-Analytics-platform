from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import get_settings

# Explicit constraint names keep Alembic migrations stable and readable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def make_engine(database_url: str | None = None) -> Engine:
    return create_engine(database_url or get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_engine() -> Engine:
    return make_engine()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards."""
    with Session(get_engine()) as session:
        yield session

