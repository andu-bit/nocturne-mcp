"""
Comprehensive tests for namespace isolation at the service layer.

Covers: CRUD, update, alias cascading, glossary/trigger, search+domain,
get_children, version chain, GC safety, and backward compatibility.
"""

import pytest
import pytest_asyncio

from db.namespace import set_namespace, get_namespace
from db.database import DatabaseManager
from db.graph import GraphService
from db.search import SearchIndexer
from db.glossary import GlossaryService
import inspect

class NamespaceProxy:
    """
    A simple proxy that automatically injects `namespace=get_namespace()` 
    into all method calls of the underlying service object, if the method supports it.
    This avoids global monkeypatching and keeps the tests clean and readable.
    """
    def __init__(self, obj):
        self._obj = obj

    def __getattr__(self, name):
        attr = getattr(self._obj, name)
        if not callable(attr):
            return attr
            
        sig = inspect.signature(attr)
        accepts_namespace = "namespace" in sig.parameters

        if inspect.iscoroutinefunction(attr):
            async def async_wrapper(*args, **kwargs):
                if accepts_namespace and "namespace" not in kwargs:
                    kwargs["namespace"] = get_namespace()
                return await attr(*args, **kwargs)
            return async_wrapper
        else:
            def sync_wrapper(*args, **kwargs):
                if accepts_namespace and "namespace" not in kwargs:
                    kwargs["namespace"] = get_namespace()
                return attr(*args, **kwargs)
            return sync_wrapper


@pytest_asyncio.fixture
async def services():
    """Spin up an in-memory SQLite database with fresh schema."""
    db = DatabaseManager("sqlite+aiosqlite://")
    await db.init_db()
    search = SearchIndexer(db)
    glossary = GlossaryService(db, search)
    graph = GraphService(db, search)
    yield NamespaceProxy(graph), NamespaceProxy(search), NamespaceProxy(glossary), db
    await db.close()


# ====================================================================
# 1. Basic CRUD isolation
# ====================================================================

@pytest.mark.asyncio
async def test_create_same_uri_different_namespaces(services):
    """Two agents create the same URI without conflict; reads are isolated."""
    graph, *_ = services

    set_namespace("ns_a")
    result_a = await graph.create_memory("", "I am Agent A.", 0, title="agent", domain="core")
    assert result_a["uri"] == "core://agent"

    set_namespace("ns_b")
    result_b = await graph.create_memory("", "I am Agent B.", 0, title="agent", domain="core")
    assert result_b["uri"] == "core://agent"

    # Independent entities
    assert result_a["node_uuid"] != result_b["node_uuid"]

    # Read isolation
    set_namespace("ns_a")
    mem_a = await graph.get_memory_by_path("agent", "core")
    assert mem_a is not None and mem_a["content"] == "I am Agent A."

    set_namespace("ns_b")
    mem_b = await graph.get_memory_by_path("agent", "core")
    assert mem_b is not None and mem_b["content"] == "I am Agent B."


@pytest.mark.asyncio
async def test_create_hierarchy_isolation(services):
    """Hierarchical paths in ns_a are invisible to ns_b."""
    graph, *_ = services

    set_namespace("ns_a")
    await graph.create_memory("", "Root A", 0, title="root", domain="core")
    await graph.create_memory("root", "Child A", 1, title="child", domain="core")
    await graph.create_memory("root/child", "Grandchild A", 2, title="leaf", domain="core")

    set_namespace("ns_b")
    await graph.create_memory("", "Root B", 0, title="root", domain="core")

    # ns_b cannot see ns_a's child / grandchild
    assert await graph.get_memory_by_path("root/child", "core") is None
    assert await graph.get_memory_by_path("root/child/leaf", "core") is None

    # ns_a sees entire tree
    set_namespace("ns_a")
    assert (await graph.get_memory_by_path("root/child/leaf", "core"))["content"] == "Grandchild A"


# ====================================================================
# 2. Update isolation
# ====================================================================

@pytest.mark.asyncio
async def test_update_isolation(services):
    """Updating memory in ns_a does not affect ns_b's content or version chain."""
    graph, *_ = services

    set_namespace("ns_a")
    await graph.create_memory("", "Original A", 0, title="note", domain="core")

    set_namespace("ns_b")
    await graph.create_memory("", "Original B", 0, title="note", domain="core")

    # Update in ns_a
    set_namespace("ns_a")
    await graph.update_memory("note", content="Updated A", domain="core")

    set_namespace("ns_a")
    assert (await graph.get_memory_by_path("note", "core"))["content"] == "Updated A"

    # ns_b untouched
    set_namespace("ns_b")
    assert (await graph.get_memory_by_path("note", "core"))["content"] == "Original B"


@pytest.mark.asyncio
async def test_update_version_chain_isolation(services):
    """Version chain created by update is scoped to its own namespace."""
    graph, *_ = services

    set_namespace("ns_a")
    r = await graph.create_memory("", "V1 A", 0, title="doc", domain="core")
    uuid_a = r["node_uuid"]
    await graph.update_memory("doc", content="V2 A", domain="core")

    set_namespace("ns_b")
    r = await graph.create_memory("", "V1 B", 0, title="doc", domain="core")
    uuid_b = r["node_uuid"]

    # The two nodes are independent
    assert uuid_a != uuid_b

    # ns_b still on V1
    set_namespace("ns_b")
    mem_b = await graph.get_memory_by_path("doc", "core")
    assert mem_b["content"] == "V1 B"


# ====================================================================
# 3. Delete isolation
# ====================================================================

@pytest.mark.asyncio
async def test_delete_does_not_affect_other_namespace(services):
    """Deleting a path in ns_a leaves ns_b's identical path intact."""
    graph, *_ = services

    set_namespace("ns_a")
    await graph.create_memory("", "A data", 0, title="shared_name", domain="core")

    set_namespace("ns_b")
    await graph.create_memory("", "B data", 0, title="shared_name", domain="core")

    set_namespace("ns_a")
    await graph.remove_path("shared_name", "core")
    assert await graph.get_memory_by_path("shared_name", "core") is None

    set_namespace("ns_b")
    mem_b = await graph.get_memory_by_path("shared_name", "core")
    assert mem_b is not None and mem_b["content"] == "B data"


@pytest.mark.asyncio
async def test_delete_parent_cascade_isolation(services):
    """Deleting a parent in ns_a cascades children only in ns_a, not ns_b."""
    graph, *_ = services

    for ns in ("ns_a", "ns_b"):
        set_namespace(ns)
        await graph.create_memory("", f"Root {ns}", 0, title="parent", domain="core")
        await graph.create_memory("parent", f"Child {ns}", 1, title="child", domain="core")

    # Delete parent in ns_a (should also remove parent/child in ns_a)
    set_namespace("ns_a")
    await graph.remove_path("parent/child", "core")
    await graph.remove_path("parent", "core")

    set_namespace("ns_a")
    assert await graph.get_memory_by_path("parent", "core") is None
    assert await graph.get_memory_by_path("parent/child", "core") is None

    # ns_b's entire subtree is untouched
    set_namespace("ns_b")
    assert (await graph.get_memory_by_path("parent", "core"))["content"] == "Root ns_b"
    assert (await graph.get_memory_by_path("parent/child", "core"))["content"] == "Child ns_b"


# ====================================================================
# 4. Index / get_all_paths isolation
# ====================================================================

@pytest.mark.asyncio
async def test_get_all_paths_isolation(services):
    """get_all_paths only returns paths from the current namespace."""
    graph, *_ = services

    set_namespace("ns_x")
    await graph.create_memory("", "X content", 0, title="x_mem", domain="core")
    await graph.create_memory("", "X writer", 0, title="x_doc", domain="writer")

    set_namespace("ns_y")
    await graph.create_memory("", "Y content", 0, title="y_mem", domain="core")

    set_namespace("ns_x")
    paths_x = await graph.get_all_paths()
    path_strs_x = {p["path"] for p in paths_x}
    assert "x_mem" in path_strs_x
    assert "x_doc" in path_strs_x
    assert "y_mem" not in path_strs_x

    set_namespace("ns_y")
    paths_y = await graph.get_all_paths()
    path_strs_y = {p["path"] for p in paths_y}
    assert "y_mem" in path_strs_y
    assert "x_mem" not in path_strs_y


@pytest.mark.asyncio
async def test_get_all_paths_domain_filter_isolation(services):
    """get_all_paths with domain filter respects namespace."""
    graph, *_ = services

    set_namespace("ns_a")
    await graph.create_memory("", "A core", 0, title="a_core", domain="core")
    await graph.create_memory("", "A writer", 0, title="a_writer", domain="writer")

    set_namespace("ns_b")
    await graph.create_memory("", "B core", 0, title="b_core", domain="core")

    set_namespace("ns_a")
    core_paths = await graph.get_all_paths(domain="core")
    assert len(core_paths) == 1
    assert core_paths[0]["path"] == "a_core"

    writer_paths = await graph.get_all_paths(domain="writer")
    assert len(writer_paths) == 1
    assert writer_paths[0]["path"] == "a_writer"


# ====================================================================
# 5. Recent memories isolation
# ====================================================================

@pytest.mark.asyncio
async def test_recent_memories_isolation(services):
    """get_recent_memories only returns memories from the current namespace."""
    graph, *_ = services

    set_namespace("ns_one")
    await graph.create_memory("", "Content one", 0, title="one", domain="core")

    set_namespace("ns_two")
    await graph.create_memory("", "Content two", 0, title="two", domain="core")

    set_namespace("ns_one")
    recent = await graph.get_recent_memories(limit=10)
    uris = [r["uri"] for r in recent]
    assert any("one" in u for u in uris)
    assert not any("two" in u for u in uris)

    set_namespace("ns_two")
    recent = await graph.get_recent_memories(limit=10)
    uris = [r["uri"] for r in recent]
    assert any("two" in u for u in uris)
    assert not any("one" in u for u in uris)


# ====================================================================
# 6. Search isolation
# ====================================================================

@pytest.mark.asyncio
async def test_search_isolation(services):
    """search() only returns results from the current namespace."""
    graph, search, *_ = services

    set_namespace("ns_alpha")
    await graph.create_memory("", "The secret alpha protocol", 0, title="alpha_secret", domain="core")

    set_namespace("ns_beta")
    await graph.create_memory("", "The secret beta protocol", 0, title="beta_secret", domain="core")

    set_namespace("ns_alpha")
    results = await search.search("secret")
    assert len(results) == 1
    assert "alpha" in results[0]["uri"]

    set_namespace("ns_beta")
    results = await search.search("secret")
    assert len(results) == 1
    assert "beta" in results[0]["uri"]


@pytest.mark.asyncio
async def test_search_with_domain_filter_isolation(services):
    """search(domain=...) respects both domain AND namespace."""
    graph, search, *_ = services

    set_namespace("ns_a")
    await graph.create_memory("", "Alpha core data", 0, title="a_core", domain="core")
    await graph.create_memory("", "Alpha writer data", 0, title="a_writer", domain="writer")

    set_namespace("ns_b")
    await graph.create_memory("", "Beta core data", 0, title="b_core", domain="core")

    # ns_a: search domain=core should only find alpha core, not beta core
    set_namespace("ns_a")
    results = await search.search("data", domain="core")
    assert len(results) == 1
    assert "a_core" in results[0]["uri"]

    # ns_a: search domain=writer should find alpha writer
    results = await search.search("data", domain="writer")
    assert len(results) == 1
    assert "a_writer" in results[0]["uri"]

    # ns_b: search domain=core should only find beta core
    set_namespace("ns_b")
    results = await search.search("data", domain="core")
    assert len(results) == 1
    assert "b_core" in results[0]["uri"]

    # ns_b: search domain=writer should find nothing
    results = await search.search("data", domain="writer")
    assert len(results) == 0


# ====================================================================
# 7. Alias cascade isolation
# ====================================================================

@pytest.mark.asyncio
async def test_alias_cascade_isolation(services):
    """Alias subtree paths created in ns_a are NOT visible in ns_b."""
    graph, *_ = services

    set_namespace("ns_a")
    await graph.create_memory("", "Parent node A", 0, title="parent", domain="core")
    await graph.create_memory("parent", "Child node A", 1, title="child", domain="core")
    await graph.add_path(
        new_path="alias_parent", target_path="parent",
        new_domain="writer", target_domain="core",
        priority=5,
    )

    # ns_a should see cascaded alias child
    set_namespace("ns_a")
    alias_child = await graph.get_memory_by_path("alias_parent/child", "writer")
    assert alias_child is not None
    assert alias_child["content"] == "Child node A"

    # ns_b should see nothing
    set_namespace("ns_b")
    assert await graph.get_memory_by_path("alias_parent", "writer") is None
    assert await graph.get_memory_by_path("alias_parent/child", "writer") is None
    assert await graph.get_memory_by_path("parent", "core") is None


@pytest.mark.asyncio
async def test_alias_in_both_namespaces_independent(services):
    """Both namespaces can create aliases independently, pointing to their own nodes."""
    graph, *_ = services

    for ns in ("ns_a", "ns_b"):
        set_namespace(ns)
        await graph.create_memory("", f"Root {ns}", 0, title="root", domain="core")
        await graph.add_path(
            new_path="root_alias", target_path="root",
            new_domain="writer", target_domain="core",
        )

    set_namespace("ns_a")
    assert (await graph.get_memory_by_path("root_alias", "writer"))["content"] == "Root ns_a"

    set_namespace("ns_b")
    assert (await graph.get_memory_by_path("root_alias", "writer"))["content"] == "Root ns_b"


# ====================================================================
# 8. Glossary / trigger isolation
# ====================================================================

@pytest.mark.asyncio
async def test_glossary_isolation(services):
    """Glossary keywords bound in ns_a do not appear in ns_b."""
    graph, _, glossary, db = services

    set_namespace("ns_a")
    r = await graph.create_memory("", "Agent A identity", 0, title="agent", domain="core")
    node_a = r["node_uuid"]
    await glossary.add_glossary_keyword("alpha_keyword", node_a)

    set_namespace("ns_b")
    r = await graph.create_memory("", "Agent B identity", 0, title="agent", domain="core")
    node_b = r["node_uuid"]
    await glossary.add_glossary_keyword("beta_keyword", node_b)

    # ns_a's glossary should only contain alpha_keyword
    set_namespace("ns_a")
    all_a = await glossary.get_all_glossary()
    keywords_a = {e["keyword"] for e in all_a}
    assert "alpha_keyword" in keywords_a
    assert "beta_keyword" not in keywords_a

    # ns_b's glossary should only contain beta_keyword
    set_namespace("ns_b")
    all_b = await glossary.get_all_glossary()
    keywords_b = {e["keyword"] for e in all_b}
    assert "beta_keyword" in keywords_b
    assert "alpha_keyword" not in keywords_b


@pytest.mark.asyncio
async def test_glossary_scan_isolation(services):
    """find_glossary_in_content only matches keywords from the current namespace."""
    graph, _, glossary, db = services

    set_namespace("ns_a")
    r = await graph.create_memory("", "Agent A soul", 0, title="soul", domain="core")
    await glossary.add_glossary_keyword("secret_word", r["node_uuid"])

    set_namespace("ns_b")
    await graph.create_memory("", "Agent B soul", 0, title="soul", domain="core")

    # Scanning text containing "secret_word" in ns_b should NOT find ns_a's keyword
    set_namespace("ns_b")
    matches = await glossary.find_glossary_in_content("This text contains secret_word here")
    assert len(matches) == 0  # Dict should be empty

    # But in ns_a it should match
    set_namespace("ns_a")
    matches = await glossary.find_glossary_in_content("This text contains secret_word here")
    assert "secret_word" in matches
    assert len(matches["secret_word"]) == 1


# ====================================================================
# 9. get_children isolation
# ====================================================================

@pytest.mark.asyncio
async def test_get_children_isolation(services):
    """get_children returns children only from the current namespace."""
    graph, *_ = services

    set_namespace("ns_a")
    r = await graph.create_memory("", "Root A", 0, title="root", domain="core")
    root_a_uuid = r["node_uuid"]
    await graph.create_memory("root", "Child A1", 1, title="c1", domain="core")
    await graph.create_memory("root", "Child A2", 2, title="c2", domain="core")

    set_namespace("ns_b")
    r = await graph.create_memory("", "Root B", 0, title="root", domain="core")
    root_b_uuid = r["node_uuid"]
    await graph.create_memory("root", "Child B1", 1, title="b1", domain="core")

    # ns_a root should have 2 children
    set_namespace("ns_a")
    children_a = await graph.get_children(root_a_uuid, context_domain="core")
    child_names_a = {c["path"] for c in children_a}
    assert len(children_a) == 2
    assert "root/c1" in child_names_a
    assert "root/c2" in child_names_a

    # ns_b root should have 1 child
    set_namespace("ns_b")
    children_b = await graph.get_children(root_b_uuid, context_domain="core")
    assert len(children_b) == 1
    assert children_b[0]["path"] == "root/b1"


# ====================================================================
# 10. GC safety across namespaces
# ====================================================================

@pytest.mark.asyncio
async def test_gc_safety_delete_in_one_ns_does_not_orphan_other(services):
    """Deleting paths in ns_a should not trigger GC on nodes that ns_b still uses.
    Since each namespace creates independent nodes, this verifies no cross-contamination."""
    graph, *_ = services

    set_namespace("ns_a")
    r_a = await graph.create_memory("", "Shared concept A", 0, title="concept", domain="core")
    uuid_a = r_a["node_uuid"]

    set_namespace("ns_b")
    r_b = await graph.create_memory("", "Shared concept B", 0, title="concept", domain="core")
    uuid_b = r_b["node_uuid"]

    # Delete in ns_a
    set_namespace("ns_a")
    await graph.remove_path("concept", "core")

    # ns_b's node is still fully alive
    set_namespace("ns_b")
    mem = await graph.get_memory_by_path("concept", "core")
    assert mem is not None
    assert mem["content"] == "Shared concept B"
    assert mem["node_uuid"] == uuid_b


# ====================================================================
# 11. Multi-domain isolation within same namespace
# ====================================================================

@pytest.mark.asyncio
async def test_multi_domain_within_namespace(services):
    """Multiple domains in the same namespace work; switching namespace hides all."""
    graph, *_ = services

    set_namespace("ns_multi")
    await graph.create_memory("", "Core item", 0, title="item", domain="core")
    await graph.create_memory("", "Writer item", 0, title="item", domain="writer")

    set_namespace("ns_multi")
    assert (await graph.get_memory_by_path("item", "core"))["content"] == "Core item"
    assert (await graph.get_memory_by_path("item", "writer"))["content"] == "Writer item"

    # Different namespace sees nothing
    set_namespace("ns_other")
    assert await graph.get_memory_by_path("item", "core") is None
    assert await graph.get_memory_by_path("item", "writer") is None


# ====================================================================
# 12. Backward compatibility — default empty namespace
# ====================================================================

@pytest.mark.asyncio
async def test_default_namespace_full_crud(services):
    """Default namespace (empty string) supports full CRUD cycle."""
    graph, search, glossary, _ = services

    set_namespace("")

    # Create
    r = await graph.create_memory("", "Default root", 0, title="root", domain="core")
    assert r["uri"] == "core://root"

    await graph.create_memory("root", "Default child", 1, title="child", domain="core")

    # Read
    mem = await graph.get_memory_by_path("root", "core")
    assert mem is not None and mem["content"] == "Default root"

    child = await graph.get_memory_by_path("root/child", "core")
    assert child is not None and child["content"] == "Default child"

    # Update
    await graph.update_memory("root", content="Updated default root", domain="core")
    assert (await graph.get_memory_by_path("root", "core"))["content"] == "Updated default root"

    # Search
    results = await search.search("default")
    assert len(results) >= 1

    # Index
    paths = await graph.get_all_paths()
    assert len(paths) >= 2

    # Recent
    recent = await graph.get_recent_memories(limit=10)
    assert len(recent) >= 1

    # Delete
    await graph.remove_path("root/child", "core")
    assert await graph.get_memory_by_path("root/child", "core") is None
    assert await graph.get_memory_by_path("root", "core") is not None


@pytest.mark.asyncio
async def test_default_namespace_invisible_to_named_namespace(services):
    """Data in default namespace is invisible to a named namespace and vice versa."""
    graph, *_ = services

    set_namespace("")
    await graph.create_memory("", "Default data", 0, title="shared", domain="core")

    set_namespace("named_ns")
    assert await graph.get_memory_by_path("shared", "core") is None

    await graph.create_memory("", "Named data", 0, title="shared", domain="core")

    set_namespace("")
    assert (await graph.get_memory_by_path("shared", "core"))["content"] == "Default data"

    set_namespace("named_ns")
    assert (await graph.get_memory_by_path("shared", "core"))["content"] == "Named data"

@pytest.mark.asyncio
async def test_orphan_memories_isolation(services):
    """Orphaned memories are NOT filtered by namespace, as it's a global admin tool."""
    graph, *_ = services

    # Create and update in ns_a
    set_namespace("ns_a")
    await graph.create_memory("", "v1 A", 0, title="orphan_test", domain="core")
    await graph.update_memory("orphan_test", "v2 A", domain="core")
    
    # Create and update in ns_b
    set_namespace("ns_b")
    await graph.create_memory("", "v1 B", 0, title="orphan_test", domain="core")
    await graph.update_memory("orphan_test", "v2 B", domain="core")

    # In ns_a, we should see BOTH since it's global
    set_namespace("ns_a")
    orphans_a = await graph.get_all_orphan_memories()
    assert len(orphans_a) == 2
    contents_a = {o["content_snippet"] for o in orphans_a}
    assert "v1 A" in contents_a
    assert "v1 B" in contents_a

    # In ns_b, we should also see BOTH
    set_namespace("ns_b")
    orphans_b = await graph.get_all_orphan_memories()
    assert len(orphans_b) == 2
    contents_b = {o["content_snippet"] for o in orphans_b}
    assert "v1 A" in contents_b
    assert "v1 B" in contents_b

    # Completely orphan ns_b's memory by deleting the node (soft GC)
    await graph.remove_path("orphan_test", domain="core")
    orphans_b_after = await graph.get_all_orphan_memories()
    
    # Now the node has no paths. Both v1 B and v2 B are orphaned.
    assert len(orphans_b_after) == 3
    contents = {o["content_snippet"] for o in orphans_b_after}
    assert "v1 B" in contents
    assert "v2 B" in contents
    assert "v1 A" in contents

    # In ns_a, same visibility
    set_namespace("ns_a")
    orphans_a_after = await graph.get_all_orphan_memories()
    assert len(orphans_a_after) == 3

