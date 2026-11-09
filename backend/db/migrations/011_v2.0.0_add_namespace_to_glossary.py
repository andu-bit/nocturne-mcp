import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

async def up(engine: AsyncEngine):
    """
    Version: v2.0.0
    Add namespace column to glossary_keywords table for multi-agent isolation.
    """
    is_postgres = "postgresql" in str(engine.url)

    async with engine.begin() as conn:
        if is_postgres:
            # PostgreSQL
            await conn.execute(text(
                "ALTER TABLE glossary_keywords ADD COLUMN IF NOT EXISTS namespace VARCHAR(64) NOT NULL DEFAULT ''"
            ))
            await conn.execute(text("ALTER TABLE glossary_keywords DROP CONSTRAINT IF EXISTS uq_glossary_keyword_node"))
            await conn.execute(text(
                "ALTER TABLE glossary_keywords ADD CONSTRAINT uq_glossary_keyword_node UNIQUE (keyword, node_uuid, namespace)"
            ))
        else:
            # SQLite: recreate table
            await conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS glossary_keywords_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    node_uuid TEXT NOT NULL REFERENCES nodes(uuid) ON DELETE CASCADE,
                    namespace VARCHAR(64) NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_glossary_keyword_node UNIQUE(keyword, node_uuid, namespace)
                )
                """
            ))
            await conn.execute(text(
                """
                INSERT OR IGNORE INTO glossary_keywords_new (id, keyword, node_uuid, namespace, created_at)
                SELECT id, keyword, node_uuid, '', created_at FROM glossary_keywords
                """
            ))
            await conn.execute(text("DROP TABLE glossary_keywords"))
            await conn.execute(text("ALTER TABLE glossary_keywords_new RENAME TO glossary_keywords"))
            
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_glossary_keyword "
                "ON glossary_keywords(keyword)"
            ))

    logger.info(
        "Migration 011: added namespace column to glossary_keywords "
        "(multi-agent isolation support)"
    )
