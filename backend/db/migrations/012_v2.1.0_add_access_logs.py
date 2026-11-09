import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

async def up(engine: AsyncEngine):
    """
    Version: v2.1.0
    Add last_accessed_at to nodes, and create memory_access_logs table.
    """
    is_postgres = "postgresql" in str(engine.url)

    async with engine.begin() as conn:
        if is_postgres:
            # PostgreSQL
            await conn.execute(text(
                "ALTER TABLE nodes ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMP NULL"
            ))
            await conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS memory_access_logs (
                    id SERIAL PRIMARY KEY,
                    node_uuid VARCHAR(36) NOT NULL REFERENCES nodes(uuid) ON DELETE CASCADE,
                    namespace VARCHAR(64) NOT NULL DEFAULT '',
                    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    context VARCHAR(64) NULL
                )
                """
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_memory_access_logs_node_uuid ON memory_access_logs(node_uuid)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_memory_access_logs_accessed_at ON memory_access_logs(accessed_at)"
            ))
        else:
            # SQLite
            # SQLite ALTER TABLE ADD COLUMN allows NULL values
            try:
                await conn.execute(text(
                    "ALTER TABLE nodes ADD COLUMN last_accessed_at TIMESTAMP NULL"
                ))
            except Exception as e:
                # Column might already exist
                if "duplicate column name" not in str(e).lower():
                    raise

            await conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS memory_access_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_uuid VARCHAR(36) NOT NULL REFERENCES nodes(uuid) ON DELETE CASCADE,
                    namespace VARCHAR(64) NOT NULL DEFAULT '',
                    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    context VARCHAR(64) NULL
                )
                """
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_memory_access_logs_node_uuid ON memory_access_logs(node_uuid)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_memory_access_logs_accessed_at ON memory_access_logs(accessed_at)"
            ))

    logger.info("Migration 012: added last_accessed_at to nodes and created memory_access_logs table")