"""
End-to-end integration tests: all 7 MCP tools with namespace isolation.

Test matrix:
  1. Full CRUD flow with two agents (read/create/update/delete/alias/trigger/search)
  2. system://boot isolation
  3. system://index and system://index/<domain> isolation
  4. system://recent isolation
  5. system://glossary cross-check (agent_b must not see agent_a's triggers)
  6. search_memory with domain filter + namespace
  7. Delete cascade (parent delete in ns_a doesn't affect ns_b)
  8. Backward compatibility (default namespace full flow)
"""

import os
import sys
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["SKIP_DB_INIT"] = "true"
os.environ["VALID_DOMAINS"] = "core,writer,game,notes,system"
os.environ["CORE_MEMORY_URIS"] = "core://agent,core://my_user"

from db.namespace import set_namespace
from db.database import DatabaseManager
from db.graph import GraphService
from db.search import SearchIndexer
from db.glossary import GlossaryService
import db as db_pkg


@pytest_asyncio.fixture
async def mcp_env():
    """Set up a fresh in-memory DB and patch the global service singletons."""
    _db = DatabaseManager("sqlite+aiosqlite://")
    await _db.init_db()
    _search = SearchIndexer(_db)
    _glossary = GlossaryService(_db, _search)
    _graph = GraphService(_db, _search)

    old = (db_pkg._db_manager, db_pkg._graph_service, db_pkg._search_indexer, db_pkg._glossary_service)
    db_pkg._db_manager = _db
    db_pkg._graph_service = _graph
    db_pkg._search_indexer = _search
    db_pkg._glossary_service = _glossary

    yield

    db_pkg._db_manager, db_pkg._graph_service, db_pkg._search_indexer, db_pkg._glossary_service = old
    await _db.close()


# ====================================================================
# Helper: seed both agents
# ====================================================================

async def _seed_two_agents():
    """Create standard memories for agent_a and agent_b."""
    from mcp_server import create_memory, manage_triggers

    set_namespace("agent_a")
    await create_memory(parent_uri="core://", content="I am Agent A's identity.",
                        priority=0, title="agent", disclosure="When asking who I am")
    await create_memory(parent_uri="core://agent", content="Agent A met User on 2026-01-01.",
                        priority=1, title="my_user", disclosure="When talking about my user")
    await create_memory(parent_uri="core://", content="Agent A writer notes.",
                        priority=2, title="notes", disclosure="When discussing writing")
    await manage_triggers("core://agent", add=["soul_trigger_a"])

    set_namespace("agent_b")
    await create_memory(parent_uri="core://", content="I am Agent B's identity.",
                        priority=0, title="agent", disclosure="When asking who I am")
    await manage_triggers("core://agent", add=["soul_trigger_b"])


# ====================================================================
# 1. Full CRUD + alias + triggers + search
# ====================================================================

@pytest.mark.asyncio
async def test_full_mcp_crud_with_namespace_isolation(mcp_env):
    """All 7 MCP tools work correctly; two agents are fully isolated."""
    from mcp_server import (
        read_memory, create_memory, update_memory,
        delete_memory, add_alias, manage_triggers, search_memory,
    )

    await _seed_two_agents()

    # --- Read isolation ---
    set_namespace("agent_a")
    assert "Agent A" in await read_memory("core://agent")
    assert "Agent B" not in await read_memory("core://agent")

    set_namespace("agent_b")
    assert "Agent B" in await read_memory("core://agent")
    assert "Agent A" not in await read_memory("core://agent")

    # --- Update isolation ---
    set_namespace("agent_a")
    result = await update_memory("core://agent",
                                 old_string="I am Agent A's identity.",
                                 new_string="I am Agent A's evolved identity.")
    assert "Success" in result
    assert "evolved" in await read_memory("core://agent")

    set_namespace("agent_b")
    assert "evolved" not in await read_memory("core://agent")

    # --- Alias isolation ---
    set_namespace("agent_a")
    assert "Success" in await add_alias(
        new_uri="writer://agent_copy",
        target_uri="core://agent",
        priority=5,
        disclosure="When mirroring agent identity",
    )

    set_namespace("agent_b")
    alias_b = await read_memory("writer://agent_copy")
    assert "Error" in alias_b or "not found" in alias_b

    # --- Delete isolation ---
    set_namespace("agent_a")
    assert "Success" in await delete_memory("core://agent/my_user")
    deleted = await read_memory("core://agent/my_user")
    assert "Error" in deleted or "not found" in deleted

    set_namespace("agent_b")
    assert "Agent B" in await read_memory("core://agent")


# ====================================================================
# 2. system://boot isolation
# ====================================================================

@pytest.mark.asyncio
async def test_system_boot_isolation(mcp_env):
    """system://boot loads core memories from the current namespace only."""
    from mcp_server import read_memory

    await _seed_two_agents()

    set_namespace("agent_a")
    boot_a = await read_memory("system://boot")
    assert "Agent A" in boot_a
    assert "Agent B" not in boot_a

    set_namespace("agent_b")
    boot_b = await read_memory("system://boot")
    assert "Agent B" in boot_b
    assert "Agent A" not in boot_b


@pytest.mark.asyncio
async def test_system_boot_per_namespace_uris(mcp_env):
    """Per-namespace CORE_MEMORY_URIS override the global fallback."""
    from mcp_server import read_memory

    await _seed_two_agents()

    # agent_a: boot only core://agent (skip core://my_user)
    # agent_b: boot only core://agent (its own override)
    os.environ["CORE_MEMORY_URIS__agent_a"] = "core://agent"
    os.environ["CORE_MEMORY_URIS__agent_b"] = "core://agent"
    try:
        set_namespace("agent_a")
        boot_a = await read_memory("system://boot")
        assert "Agent A" in boot_a
        # core://my_user is in the global fallback but NOT in agent_a's override
        assert "met User" not in boot_a

        set_namespace("agent_b")
        boot_b = await read_memory("system://boot")
        assert "Agent B" in boot_b
        assert "Agent A" not in boot_b
    finally:
        os.environ.pop("CORE_MEMORY_URIS__agent_a", None)
        os.environ.pop("CORE_MEMORY_URIS__agent_b", None)


@pytest.mark.asyncio
async def test_system_boot_per_namespace_empty_override(mcp_env):
    """An explicit empty CORE_MEMORY_URIS__ns should NOT fall back to the global list."""
    from mcp_server import read_memory
    
    # Mock global list with something
    os.environ["CORE_MEMORY_URIS"] = "core://global"
    
    # Mock an explicit empty list for agent_c
    os.environ["CORE_MEMORY_URIS__agent_c"] = ""
    
    try:
        set_namespace("agent_c")
        boot_c = await read_memory("system://boot")
        # Should NOT load global
        assert "core://global" not in boot_c
        assert "(No core memories loaded" in boot_c or "Loaded: 0/0" in boot_c
    finally:
        os.environ.pop("CORE_MEMORY_URIS", None)
        os.environ.pop("CORE_MEMORY_URIS__agent_c", None)


# ====================================================================
# 3. system://index and system://index/<domain>
# ====================================================================

@pytest.mark.asyncio
async def test_system_index_isolation(mcp_env):
    """system://index shows only the current namespace's memory tree."""
    from mcp_server import read_memory

    await _seed_two_agents()

    set_namespace("agent_a")
    index_a = await read_memory("system://index/core")
    assert "my_user" in index_a
    assert "notes" in index_a

    set_namespace("agent_b")
    index_b = await read_memory("system://index/core")
    assert "my_user" not in index_b
    assert "notes" not in index_b


@pytest.mark.asyncio
async def test_system_index_domain_isolation(mcp_env):
    """system://index/<domain> only shows paths in the requested domain within the namespace."""
    from mcp_server import read_memory, create_memory

    set_namespace("agent_a")
    await create_memory(parent_uri="core://", content="A core data", priority=0,
                        title="a_core", disclosure="When reviewing agent A core index")
    await create_memory(parent_uri="writer://", content="A writer data", priority=0,
                        title="a_writer", disclosure="When reviewing agent A writer index")

    set_namespace("agent_b")
    await create_memory(parent_uri="core://", content="B core data", priority=0,
                        title="b_core", disclosure="When reviewing agent B core index")

    set_namespace("agent_a")
    index_core = await read_memory("system://index/core")
    assert "a_core" in index_core
    assert "a_writer" not in index_core
    assert "b_core" not in index_core

    set_namespace("agent_b")
    index_core_b = await read_memory("system://index/core")
    assert "b_core" in index_core_b
    assert "a_core" not in index_core_b


# ====================================================================
# 4. system://recent isolation
# ====================================================================

@pytest.mark.asyncio
async def test_system_recent_isolation(mcp_env):
    """system://recent shows only the current namespace's recent memories."""
    from mcp_server import read_memory

    await _seed_two_agents()

    set_namespace("agent_a")
    recent_a = await read_memory("system://recent")
    assert "core://agent" in recent_a
    assert "my_user" in recent_a

    set_namespace("agent_b")
    recent_b = await read_memory("system://recent")
    assert "my_user" not in recent_b


# ====================================================================
# 5. system://glossary cross-check
# ====================================================================

@pytest.mark.asyncio
async def test_system_glossary_isolation(mcp_env):
    """Each agent's glossary only contains its own triggers, not the other's."""
    from mcp_server import read_memory

    await _seed_two_agents()

    set_namespace("agent_a")
    glossary_a = await read_memory("system://glossary")
    assert "soul_trigger_a" in glossary_a
    assert "soul_trigger_b" not in glossary_a

    set_namespace("agent_b")
    glossary_b = await read_memory("system://glossary")
    assert "soul_trigger_b" in glossary_b
    assert "soul_trigger_a" not in glossary_b


# ====================================================================
# 6. search_memory with domain filter + namespace
# ====================================================================

@pytest.mark.asyncio
async def test_search_memory_domain_filter_isolation(mcp_env):
    """search_memory(domain=...) respects both domain and namespace."""
    from mcp_server import search_memory

    await _seed_two_agents()

    set_namespace("agent_a")
    result = await search_memory("identity", domain="core")
    assert "Agent A" in result
    assert "Agent B" not in result

    # agent_a has no writer:// content matching "identity"
    result_writer = await search_memory("identity", domain="writer")
    assert "Agent A" not in result_writer

    set_namespace("agent_b")
    result_b = await search_memory("identity", domain="core")
    assert "Agent B" in result_b
    assert "Agent A" not in result_b


# ====================================================================
# 7. Delete cascade isolation
# ====================================================================

@pytest.mark.asyncio
async def test_delete_cascade_isolation(mcp_env):
    """Deleting a parent in agent_a does not affect agent_b's subtree."""
    from mcp_server import create_memory, delete_memory, read_memory

    for ns in ("agent_a", "agent_b"):
        set_namespace(ns)
        await create_memory(parent_uri="core://", content=f"Parent {ns}",
                            priority=0, title="parent", disclosure=f"When reviewing parent memory in {ns}")
        await create_memory(parent_uri="core://parent", content=f"Child {ns}",
                            priority=1, title="child", disclosure=f"When reviewing child memory in {ns}")

    set_namespace("agent_a")
    await delete_memory("core://parent/child")
    await delete_memory("core://parent")

    deleted_parent = await read_memory("core://parent")
    assert "Error" in deleted_parent or "not found" in deleted_parent

    set_namespace("agent_b")
    assert "Parent agent_b" in await read_memory("core://parent")
    assert "Child agent_b" in await read_memory("core://parent/child")


# ====================================================================
# 8. Backward compatibility — default namespace
# ====================================================================

@pytest.mark.asyncio
async def test_default_namespace_mcp_full_flow(mcp_env):
    """When no namespace is configured (empty string), all MCP tools work as before."""
    from mcp_server import (
        read_memory, create_memory, update_memory,
        delete_memory, add_alias, manage_triggers, search_memory,
    )

    set_namespace("")

    # Create
    assert "Success" in await create_memory(
        parent_uri="core://", content="Default agent identity.", priority=0,
        title="agent", disclosure="When asking who I am")
    assert "Success" in await create_memory(
        parent_uri="core://agent", content="Default user info.", priority=1,
        title="my_user", disclosure="When talking about user")

    # Read
    content = await read_memory("core://agent")
    assert "Default agent identity" in content

    # Boot
    boot = await read_memory("system://boot")
    assert "Default agent identity" in boot

    # Index
    index = await read_memory("system://index/core")
    assert "agent" in index
    assert "my_user" in index

    # Recent
    recent = await read_memory("system://recent")
    assert "core://agent" in recent

    # Update
    assert "Success" in await update_memory(
        "core://agent", old_string="Default agent identity.",
        new_string="Updated default agent identity.")

    # Search
    results = await search_memory("identity")
    assert "Updated default agent" in results

    # Alias
    assert "Success" in await add_alias(
        new_uri="writer://agent_ref",
        target_uri="core://agent",
        priority=5,
        disclosure="When mirroring default agent identity",
    )

    alias_content = await read_memory("writer://agent_ref")
    assert "Updated default agent" in alias_content

    # Triggers
    assert "Added" in await manage_triggers("core://agent", add=["default_trigger"])
    glossary = await read_memory("system://glossary")
    assert "default_trigger" in glossary

    # Delete
    assert "Success" in await delete_memory("core://agent/my_user")
    deleted = await read_memory("core://agent/my_user")
    assert "Error" in deleted or "not found" in deleted

    # Parent still alive
    assert "Updated default agent" in await read_memory("core://agent")
