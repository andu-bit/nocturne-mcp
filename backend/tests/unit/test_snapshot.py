from db.snapshot import ChangesetStore


def test_changeset_store_overwrites_after_state_but_keeps_before_state(tmp_path):
    store = ChangesetStore(snapshot_dir=str(tmp_path))

    store.record(
        "edges",
        {"id": 1, "priority": 1, "disclosure": "before"},
        {"id": 1, "priority": 2, "disclosure": "mid"},
    )
    store.record(
        "edges",
        {"id": 1, "priority": 2, "disclosure": "mid"},
        {"id": 1, "priority": 3, "disclosure": "after"},
    )

    row = store.get_snapshot_view()[0]["edges:1"]

    assert row["before"]["priority"] == 1
    assert row["after"]["priority"] == 3
    assert store.get_change_count() == 1


def test_changeset_store_gc_removes_create_then_delete_subtree_noise(tmp_path):
    store = ChangesetStore(snapshot_dir=str(tmp_path))

    created = {
        "nodes": [{"uuid": "node-1"}],
        "memories": [{"id": 1, "node_uuid": "node-1"}],
        "edges": [{"id": 1, "parent_uuid": "root", "child_uuid": "node-1"}],
        "paths": [{"namespace": "", "domain": "core", "path": "temp", "edge_id": 1}],
    }
    deleted_path = {
        "paths": [{"namespace": "", "domain": "core", "path": "temp", "edge_id": 1}],
    }

    store.record_many(before_state={}, after_state=created)
    store.record_many(before_state=deleted_path, after_state={})

    assert store.get_change_count() == 0
    assert store.get_snapshot_view()[0] == {}


def test_changeset_store_migrates_legacy_keys_on_load(tmp_path):
    import json
    
    # Manually write a legacy changeset.json (pre-namespace)
    legacy_data = {
        "rows": {
            "paths:core|legacy_path": {
                "table": "paths",
                "before": {"domain": "core", "path": "legacy_path", "edge_id": 1},
                "after": {"domain": "core", "path": "legacy_path", "edge_id": 2}
            }
        }
    }
    with open(tmp_path / "changeset.json", "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)
        
    store = ChangesetStore(snapshot_dir=str(tmp_path))
    
    # 1. verify _load() correctly migrated it in memory
    rows = store.get_snapshot_view()[0]
    assert "paths:core|legacy_path" not in rows
    assert "paths:|core|legacy_path" in rows
    
    row = rows["paths:|core|legacy_path"]
    assert row["before"]["namespace"] == ""
    assert row["after"]["namespace"] == ""
    
    # 2. verify we can remove it (which uses the canonical key paths:|core|legacy_path internally)
    removed = store.remove_keys(["paths:|core|legacy_path"])
    assert removed == 1
    assert store.get_change_count() == 0
    assert store.get_snapshot_view()[0] == {}

