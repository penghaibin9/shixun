from os import getenv
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def database_url() -> str:
    value = getenv("YUEKE_DATABASE_URL")
    if not value:
        raise RuntimeError("缺少 YUEKE_DATABASE_URL，实验定义接口拒绝连接数据库")
    return value


@lru_cache(maxsize=8)
def _cached_session_factory(url: str) -> sessionmaker[Session]:
    engine = create_engine(url, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_session_factory(url: str | None = None) -> sessionmaker[Session]:
    return _cached_session_factory(url or database_url())


def get_session():
    session = create_session_factory()()
    try:
        yield session
    finally:
        session.close()
