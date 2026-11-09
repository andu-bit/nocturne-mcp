import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from db.search_terms import build_document_search_terms

logger = logging.getLogger(__name__)


async def up(engine: AsyncEngine):
    """
    Version: v2.0.0
    Add namespace column to paths and search_documents tables for multi-agent isolation.

    The namespace column becomes part of the composite primary key so that
    different agents (identified by namespace) can have independent path trees
    within the same database.

    Existing data is assigned namespace='' (empty string = default namespace).
    """
    is_postgres = "postgresql" in str(engine.url)
    false_val = "FALSE" if is_postgres else "0"
    keyword_agg = (
        "COALESCE((SELECT string_agg(keyword, ' ') FROM glossary_keywords g "
        "WHERE g.node_uuid = e.child_uuid), '')"
        if is_postgres
        else "COALESCE((SELECT group_concat(keyword, ' ') FROM glossary_keywords g "
        "WHERE g.node_uuid = e.child_uuid), '')"
    )

    async with engine.begin() as conn:
        if is_postgres:
            # --- PostgreSQL: ALTER TABLE to add column and rebuild PK ---

            # paths table
            await conn.execute(text(
                "ALTER TABLE paths ADD COLUMN IF NOT EXISTS namespace VARCHAR(64) NOT NULL DEFAULT ''"
            ))
            await conn.execute(text("ALTER TABLE paths DROP CONSTRAINT IF EXISTS paths_pkey"))
            await conn.execute(text(
                "ALTER TABLE paths ADD PRIMARY KEY (namespace, domain, path)"
            ))

            # search_documents table
            await conn.execute(text(
                "ALTER TABLE search_documents ADD COLUMN IF NOT EXISTS namespace VARCHAR(64) NOT NULL DEFAULT ''"
            ))
            await conn.execute(text(
                "ALTER TABLE search_documents DROP CONSTRAINT IF EXISTS search_documents_pkey"
            ))
            await conn.execute(text(
                "ALTER TABLE search_documents ADD PRIMARY KEY (namespace, domain, path)"
            ))

            # Rebuild the GIN FTS index to include namespace
            search_text_expr = (
                "coalesce(path, '') || ' ' || "
                "coalesce(uri, '') || ' ' || "
                "coalesce(content, '') || ' ' || "
                "coalesce(disclosure, '') || ' ' || "
                "coalesce(search_terms, '')"
            )
            await conn.execute(text("DROP INDEX IF EXISTS idx_search_documents_fts"))
            await conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_search_documents_fts "
                f"ON search_documents USING GIN (to_tsvector('simple', {search_text_expr}))"
            ))

        else:
            # --- SQLite: recreate tables (SQLite cannot ALTER PRIMARY KEY) ---

            # 1. Recreate paths table with namespace in PK
            await conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS paths_new (
                    namespace VARCHAR(64) NOT NULL DEFAULT '',
                    domain VARCHAR(64) NOT NULL DEFAULT 'core',
                    path VARCHAR(512) NOT NULL,
                    edge_id INTEGER REFERENCES edges(id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (namespace, domain, path)
                )
                """
            ))
            await conn.execute(text(
                """
                INSERT OR IGNORE INTO paths_new (namespace, domain, path, edge_id, created_at)
                SELECT '', domain, path, edge_id, created_at FROM paths
                """
            ))
            await conn.execute(text("DROP TABLE paths"))
            await conn.execute(text("ALTER TABLE paths_new RENAME TO paths"))

            # 2. Drop old FTS table (will be recreated below)
            await conn.execute(text("DROP TABLE IF EXISTS search_documents_fts"))

            # 3. Recreate search_documents table with namespace in PK
            await conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS search_documents_new (
                    namespace VARCHAR(64) NOT NULL DEFAULT '',
                    domain VARCHAR(64) NOT NULL,
                    path VARCHAR(512) NOT NULL,
                    node_uuid VARCHAR(36) NOT NULL REFERENCES nodes(uuid) ON DELETE CASCADE,
                    memory_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    uri TEXT NOT NULL,
                    content TEXT NOT NULL,
                    disclosure TEXT,
                    search_terms TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (namespace, domain, path)
                )
                """
            ))
            await conn.execute(text(
                """
                INSERT OR IGNORE INTO search_documents_new
                    (namespace, domain, path, node_uuid, memory_id, uri, content,
                     disclosure, search_terms, priority, updated_at)
                SELECT '', domain, path, node_uuid, memory_id, uri, content,
                       disclosure, search_terms, priority, updated_at
                FROM search_documents
                """
            ))
            await conn.execute(text("DROP TABLE search_documents"))
            await conn.execute(text(
                "ALTER TABLE search_documents_new RENAME TO search_documents"
            ))

            # 4. Recreate indexes
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_search_documents_node_uuid "
                "ON search_documents(node_uuid)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_search_documents_memory_id "
                "ON search_documents(memory_id)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_search_documents_domain "
                "ON search_documents(domain)"
            ))

            # 5. Recreate FTS5 table with namespace column
            await conn.execute(text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS search_documents_fts
                USING fts5(
                    namespace UNINDEXED,
                    domain UNINDEXED,
                    path,
                    node_uuid UNINDEXED,
                    uri,
                    content,
                    disclosure,
                    search_terms,
                    tokenize = 'unicode61'
                )
                """
            ))

            # 6. Rebuild FTS from search_documents (all have namespace='')
            await conn.execute(text("DELETE FROM search_documents"))
            await conn.execute(text("DELETE FROM search_documents_fts"))

            raw_rows = (
                await conn.execute(text(
                    f"""
                    SELECT
                        p.namespace,
                        p.domain,
                        p.path,
                        e.child_uuid as node_uuid,
                        m.id as memory_id,
                        p.domain || '://' || p.path as uri,
                        m.content,
                        e.disclosure,
                        {keyword_agg} as glossary_text,
                        e.priority
                    FROM paths p
                    JOIN edges e ON p.edge_id = e.id
                    JOIN memories m
                      ON m.node_uuid = e.child_uuid
                     AND m.deprecated = {false_val}
                    """
                ))
            ).mappings().all()

            for row in raw_rows:
                search_terms = build_document_search_terms(
                    row["path"],
                    row["uri"],
                    row["content"],
                    row["disclosure"],
                    row["glossary_text"] or "",
                )
                await conn.execute(
                    text(
                        """
                        INSERT INTO search_documents
                            (namespace, domain, path, node_uuid, memory_id, uri, content,
                             disclosure, search_terms, priority)
                        VALUES
                            (:namespace, :domain, :path, :node_uuid, :memory_id, :uri,
                             :content, :disclosure, :search_terms, :priority)
                        """
                    ),
                    {
                        "namespace": row["namespace"],
                        "domain": row["domain"],
                        "path": row["path"],
                        "node_uuid": row["node_uuid"],
                        "memory_id": row["memory_id"],
                        "uri": row["uri"],
                        "content": row["content"],
                        "disclosure": row["disclosure"],
                        "search_terms": search_terms,
                        "priority": row["priority"],
                    },
                )

            await conn.execute(text(
                """
                INSERT INTO search_documents_fts
                    (namespace, domain, path, node_uuid, uri, content, disclosure, search_terms)
                SELECT
                    namespace, domain, path, node_uuid, uri, content,
                    coalesce(disclosure, ''), search_terms
                FROM search_documents
                """
            ))

    logger.info(
        "Migration 010: added namespace column to paths and search_documents "
        "(multi-agent isolation support)"
    )
