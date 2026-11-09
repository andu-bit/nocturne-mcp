import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def up(engine: AsyncEngine):
    """
    Version: v2.5.3
    Add presets table for managing boot URI configurations.
    """
    is_postgres = "postgresql" in str(engine.url)

    async with engine.begin() as conn:
        if is_postgres:
            await conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS presets (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    boot_uris TEXT NOT NULL DEFAULT '{}',
                    path_masks TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            ))
            await conn.execute(text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_presets_active 
                ON presets (is_active) 
                WHERE is_active = true;
                """
            ))
        else:
            await conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS presets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    boot_uris TEXT NOT NULL DEFAULT '{}',
                    path_masks TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            ))
            await conn.execute(text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_presets_active 
                ON presets (is_active) 
                WHERE is_active = 1;
                """
            ))

    logger.info("Migration 014: created presets table and enforced single active preset constraint")
