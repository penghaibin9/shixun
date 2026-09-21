from alembic import context
from sqlalchemy import engine_from_config, pool
from os import getenv

from app.common.models import Base
from app.teaching import models as teaching_models  # noqa: F401

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    database_url = getenv("YUEKE_DATABASE_URL")
    if not database_url:
        raise RuntimeError("缺少 YUEKE_DATABASE_URL，拒绝连接或升级数据库")
    config.set_main_option("sqlalchemy.url", database_url)
    engine = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
