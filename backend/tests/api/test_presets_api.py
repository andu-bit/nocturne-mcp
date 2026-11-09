from db import get_preset_service

async def test_presets_api_lifecycle(api_client):
    # Ensure presets are auto-promoted from config
    service = get_preset_service()
    await service.auto_promote_from_config()

    # 1. List presets - should at least contain the auto-promoted default preset
    response = await api_client.get("/presets")
    assert response.status_code == 200
    presets = response.json()["presets"]
    assert len(presets) >= 1
    default_preset = [p for p in presets if p["is_active"]][0]
    assert default_preset["name"] == "default"

    # 2. Create a new preset
    create_payload = {
        "name": "preset_b",
        "boot_uris": {"": ["core://agent"]},
        "activate": False,
    }
    create_response = await api_client.post("/presets", json=create_payload)
    assert create_response.status_code == 201
    preset_b = create_response.json()
    assert preset_b["name"] == "preset_b"
    assert preset_b["is_active"] is False

    # 3. Create another preset with the same name (should fail with 409)
    fail_create_response = await api_client.post("/presets", json=create_payload)
    assert fail_create_response.status_code == 409
    assert "already exists" in fail_create_response.json()["detail"]

    # 3.5. Create preset with space-padded name (should trim, find duplicate, and fail with 409)
    padded_create_payload = create_payload.copy()
    padded_create_payload["name"] = "  preset_b  "
    fail_padded_create_response = await api_client.post("/presets", json=padded_create_payload)
    assert fail_padded_create_response.status_code == 409
    assert "Preset 'preset_b' already exists" in fail_padded_create_response.json()["detail"]

    # 4. Create preset C
    create_payload_c = {
        "name": "preset_c",
        "boot_uris": {"": ["core://agent"]},
        "activate": False,
    }
    create_response_c = await api_client.post("/presets", json=create_payload_c)
    assert create_response_c.status_code == 201
    preset_c = create_response_c.json()

    # 5. Try updating preset C's name to preset B's name (should fail with 409)
    update_payload_fail = {"name": "preset_b"}
    update_response_fail = await api_client.put(f"/presets/{preset_c['id']}", json=update_payload_fail)
    assert update_response_fail.status_code == 409
    assert "already exists" in update_response_fail.json()["detail"]

    # 6. Update preset C's name to its own name (should succeed)
    update_payload_same = {"name": "preset_c"}
    update_response_same = await api_client.put(f"/presets/{preset_c['id']}", json=update_payload_same)
    assert update_response_same.status_code == 200
    assert update_response_same.json()["name"] == "preset_c"

    # 7. Update preset C's name to a new unique name (should succeed)
    update_payload_new = {"name": "preset_c_unique"}
    update_response_new = await api_client.put(f"/presets/{preset_c['id']}", json=update_payload_new)
    assert update_response_new.status_code == 200
    assert update_response_new.json()["name"] == "preset_c_unique"

    # 8. Duplicate preset_b to an existing name (preset_c_unique) (should fail with 409)
    dup_payload_fail = {"new_name": "preset_c_unique"}
    dup_response_fail = await api_client.post(f"/presets/{preset_b['id']}/duplicate", json=dup_payload_fail)
    assert dup_response_fail.status_code == 409

    # 8.5. Duplicate preset_b to an existing padded name (should trim, find duplicate, and fail with 409)
    dup_padded_payload_fail = {"new_name": "  preset_c_unique  "}
    dup_padded_response_fail = await api_client.post(f"/presets/{preset_b['id']}/duplicate", json=dup_padded_payload_fail)
    assert dup_padded_response_fail.status_code == 409
    assert "Preset 'preset_c_unique' already exists" in dup_padded_response_fail.json()["detail"]

    # 9. Duplicate preset_b to a new name (should succeed)
    dup_payload_ok = {"new_name": "preset_b_copy"}
    dup_response_ok = await api_client.post(f"/presets/{preset_b['id']}/duplicate", json=dup_payload_ok)
    assert dup_response_ok.status_code == 200
    preset_b_copy = dup_response_ok.json()
    assert preset_b_copy["name"] == "preset_b_copy"

    # 10. Activate preset_b
    act_response = await api_client.post(f"/presets/{preset_b['id']}/activate")
    assert act_response.status_code == 200
    assert act_response.json()["is_active"] is True

    # 11. Delete active preset (should fail with 400)
    del_active_response = await api_client.delete(f"/presets/{preset_b['id']}")
    assert del_active_response.status_code == 400

    # 12. Delete inactive preset (should succeed)
    del_inactive_response = await api_client.delete(f"/presets/{preset_b_copy['id']}")
    assert del_inactive_response.status_code == 200
