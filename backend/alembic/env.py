from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
from app.models import Base
from app.config import DATABASE_URL

config = context.config
if config.config_file_name is not None:
    # Код-ревью (тест-изоляция): fileConfig() по умолчанию disable_existing_loggers=True —
    # отключает НАВСЕГДА (logger.disabled=True) любой уже созданный к этому моменту логгер,
    # не упомянутый в alembic.ini явно (там сконфигурированы только root/sqlalchemy/alembic).
    # test_migrations_diagram.py вызывает command.upgrade()/downgrade() (а значит, и этот env.py)
    # много раз за сессию pytest — начиная с первого вызова, logging.getLogger("app.main")
    # (пакет services/auth и т.п., создаётся при импорте app.main для фикстуры client в conftest.py)
    # навсегда замолкал для всех ПОСЛЕДУЮЩИХ тестов сессии, включая уже упавший на этом
    # test_startup_warnings.py. disable_existing_loggers=False — обычная и рекомендуемая правка
    # именно для этого сценария (Alembic исполняется как часть более крупного приложения, а не
    # как отдельный CLI-процесс).
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def _url():
    return DATABASE_URL


def run_migrations_offline():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
