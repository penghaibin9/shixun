from os import getenv

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def database_url() -> str:
    url = getenv("YUEKE_DATABASE_URL")
    if not url:
        raise RuntimeError("缺少 YUEKE_DATABASE_URL，拒绝连接数据库")
    return url


def get_session():
    engine = create_engine(database_url(), pool_pre_ping=True)
    with Session(engine) as session:
        yield session
