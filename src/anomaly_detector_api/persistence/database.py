import logging

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import settings
from .models_db import Base

logger = logging.getLogger(__name__)


def build_engine() -> AsyncEngine:
    """Crea el AsyncEngine de SQLAlchemy a partir de `settings.database_url`."""
    return create_async_engine(settings.database_url, pool_pre_ping=True, future=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    """Crea la fábrica de sesiones asíncronas ligada al engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine: AsyncEngine) -> None:
    """
    Crea las tablas si no existen (idempotente).

    Conveniencia para desarrollo y pruebas. En despliegues serios el esquema se
    gestiona con Alembic (`alembic upgrade head`); `create_all` no recrea ni
    altera tablas existentes, por lo que ambos caminos conviven sin conflicto.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Esquema de base de datos verificado (anomaly_inferences).")
