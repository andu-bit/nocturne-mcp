import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def up(engine: AsyncEngine):
    """
    Version: v2.2.0
    Add node_uuid column to paths table and backfill from edges.child_uuid.

    This denormalizes the target node onto Path, eliminating the need
    to JOIN edges in most path-centric queries.
    """
    is_postgres = "postgresql" in str(engine.url)

    async with engine.begin() as conn:
        if is_postgres:
            await conn.execute(text(
                "ALTER TABLE paths ADD COLUMN IF NOT EXISTS "
                "node_uuid VARCHAR(36) REFERENCES nodes(uuid)"
            ))
        else:
            try:
                await conn.execute(text(
                    "ALTER TABLE paths ADD COLUMN node_uuid VARCHAR(36) "
                    "REFERENCES nodes(uuid)"
                ))
            except Exception as e:
                if "duplicate column name" not in str(e).lower():
                    raise

        # Backfill from edges.child_uuid
        await conn.execute(text(
            "UPDATE paths SET node_uuid = ("
            "  SELECT e.child_uuid FROM edges e WHERE e.id = paths.edge_id"
            ") WHERE node_uuid IS NULL AND edge_id IS NOT NULL"
        ))

        # Index for fast lookups
        if is_postgres:
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_paths_node_uuid "
                "ON paths (node_uuid)"
            ))
        else:
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_paths_node_uuid "
                "ON paths (node_uuid)"
            ))

    logger.info(
        "Migration 013: added node_uuid to paths and backfilled from edges"
    )
