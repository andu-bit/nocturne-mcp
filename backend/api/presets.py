"""
Presets API — manage boot URI presets from the admin UI.
"""

import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import get_preset_service

router = APIRouter(prefix="/presets", tags=["presets"])

_URI_RE = re.compile(r"^[a-zA-Z0-9_-]+://[a-zA-Z0-9_/\.-]*$")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PresetCreate(BaseModel):
    name: str
    boot_uris: dict[str, list[str]]
    activate: bool = False


class PresetUpdate(BaseModel):
    name: Optional[str] = None
    boot_uris: Optional[dict[str, list[str]]] = None


class PresetDuplicate(BaseModel):
    new_name: str


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_boot_uris(boot_uris: dict[str, list[str]]):
    for ns, uris in boot_uris.items():
        for uri in uris:
            if not _URI_RE.match(uri):
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid URI format: {uri}",
                )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_presets():
    """List all presets."""
    service = get_preset_service()
    presets = await service.list_presets()
    return {"presets": presets}


@router.post("", status_code=201)
async def create_preset(body: PresetCreate):
    """Create a new preset."""
    trimmed_name = body.name.strip()
    if not trimmed_name:
        raise HTTPException(status_code=422, detail="Preset name cannot be empty")

    _validate_boot_uris(body.boot_uris)

    service = get_preset_service()

    existing = await service.get_preset_by_name(trimmed_name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Preset '{trimmed_name}' already exists")

    try:
        preset = await service.create_preset(
            name=trimmed_name,
            boot_uris=body.boot_uris,
            activate=body.activate,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return preset


@router.get("/{preset_id}")
async def get_preset(preset_id: int):
    """Get a single preset by ID."""
    service = get_preset_service()
    preset = await service.get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return preset


@router.put("/{preset_id}")
async def update_preset(preset_id: int, body: PresetUpdate):
    """Update an existing preset."""
    service = get_preset_service()

    update_data = body.model_dump(exclude_unset=True)

    if "name" in update_data:
        name = update_data["name"]
        if name is None or not name.strip():
            raise HTTPException(status_code=422, detail="Preset name cannot be empty")
        trimmed_name = name.strip()
        update_data["name"] = trimmed_name

        existing = await service.get_preset_by_name(trimmed_name)
        if existing and existing["id"] != preset_id:
            raise HTTPException(status_code=409, detail=f"Preset '{trimmed_name}' already exists")

    if "boot_uris" in update_data:
        if update_data["boot_uris"] is None:
            raise HTTPException(status_code=422, detail="boot_uris cannot be null")
        _validate_boot_uris(update_data["boot_uris"])

    if not update_data:
        raise HTTPException(status_code=422, detail="No fields to update")

    try:
        result = await service.update_preset(preset_id, **update_data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not result:
        raise HTTPException(status_code=404, detail="Preset not found")
    return result


@router.delete("/{preset_id}")
async def delete_preset(preset_id: int):
    """Delete a preset. Cannot delete the active preset."""
    service = get_preset_service()
    success = await service.delete_preset(preset_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete preset: either not found or currently active",
        )
    return {"success": True}


@router.post("/{preset_id}/activate")
async def activate_preset(preset_id: int):
    """Activate a preset (deactivates all others)."""
    service = get_preset_service()
    result = await service.activate_preset(preset_id)
    if not result:
        raise HTTPException(status_code=404, detail="Preset not found")
    return result


@router.post("/{preset_id}/duplicate")
async def duplicate_preset(preset_id: int, body: PresetDuplicate):
    """Duplicate a preset with a new name."""
    trimmed_new_name = body.new_name.strip()
    if not trimmed_new_name:
        raise HTTPException(status_code=422, detail="New name cannot be empty")

    service = get_preset_service()

    existing = await service.get_preset_by_name(trimmed_new_name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Preset '{trimmed_new_name}' already exists")

    try:
        result = await service.duplicate_preset(preset_id, trimmed_new_name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not result:
        raise HTTPException(status_code=404, detail="Source preset not found")
    return result
