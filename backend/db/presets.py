"""
Preset management service.

Handles CRUD operations for boot URI presets and the auto-promotion
logic that migrates legacy config.json boot_uris into the DB on first run.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Preset
from .database import DatabaseManager

logger = logging.getLogger(__name__)


class PresetService:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    async def auto_promote_from_config(self) -> None:
        """One-time migration: if presets table is empty, seed from config.json."""
        async with self.db.session() as session:
            count = await session.scalar(
                select(func.count()).select_from(Preset)
            )
            if count and count > 0:
                return

            import config
            legacy = config.get_all_boot_uris()
            if not legacy:
                legacy = {"": []}

            preset = Preset(
                name="default",
                boot_uris=json.dumps(legacy, ensure_ascii=False),
                is_active=True,
            )
            session.add(preset)
            logger.info("Auto-promoted config.json boot_uris into 'default' preset")

    async def get_active_preset(self, session: Optional[AsyncSession] = None) -> Optional[Preset]:
        async with self.db._optional_session(session) as s:
            result = await s.execute(
                select(Preset).where(Preset.is_active == True)  # noqa: E712
            )
            return result.scalar_one_or_none()

    async def get_all_boot_uris(self) -> dict[str, list[str]]:
        """Get the full boot_uris dict (all namespaces), from active preset or config fallback."""
        active = await self.get_active_preset()
        if active:
            return json.loads(active.boot_uris)
        import config
        return config.get_all_boot_uris()

    async def get_boot_uris(self, namespace: str = "") -> list[str]:
        """Get boot URIs for a namespace from the active preset, with config fallback."""
        boot_map = await self.get_all_boot_uris()
        if namespace in boot_map:
            return boot_map[namespace]
        return boot_map.get("", [])

    async def set_boot_uris(self, namespace: str, uris: list[str]) -> None:
        """Set boot URIs for a namespace. Writes to active preset or config fallback."""
        active = await self.get_active_preset()
        if active:
            boot_map = json.loads(active.boot_uris)
            boot_map[namespace] = uris
            await self.update_preset(active.id, boot_uris=boot_map)
        else:
            import config
            config.set_boot_uris(uris, namespace)

    async def delete_boot_uris(self, namespace: str) -> bool:
        """Remove a namespace override. Returns True if it existed."""
        active = await self.get_active_preset()
        if active:
            boot_map = json.loads(active.boot_uris)
            if namespace not in boot_map:
                return False
            del boot_map[namespace]
            await self.update_preset(active.id, boot_uris=boot_map)
            return True
        else:
            import config
            return config.delete_boot_uris(namespace)

    async def rewrite_boot_uri(self, old_uri: str, new_uri: str, namespace: str) -> None:
        """Rename a URI (and its subtree prefixes) in the boot list."""
        uris = await self.get_boot_uris(namespace)
        old_prefix = old_uri + "/"
        new_prefix = new_uri + "/"
        rewritten = []
        for u in uris:
            if u == old_uri:
                rewritten.append(new_uri)
            elif u.startswith(old_prefix):
                rewritten.append(new_prefix + u[len(old_prefix):])
            else:
                rewritten.append(u)
        if rewritten != uris:
            await self.set_boot_uris(namespace, rewritten)

    async def purge_boot_uri(self, uri: str, namespace: str) -> None:
        """Remove a URI (and its subtree) from the boot list."""
        uris = await self.get_boot_uris(namespace)
        prefix = uri + "/"
        cleaned = [u for u in uris if u != uri and not u.startswith(prefix)]
        if len(cleaned) != len(uris):
            await self.set_boot_uris(namespace, cleaned)

    async def list_presets(self) -> list[dict]:
        async with self.db.session() as session:
            result = await session.execute(
                select(Preset).order_by(Preset.created_at)
            )
            presets = result.scalars().all()
            return [self._serialize(p) for p in presets]

    async def get_preset(self, preset_id: int) -> Optional[dict]:
        async with self.db.session() as session:
            preset = await session.get(Preset, preset_id)
            return self._serialize(preset) if preset else None

    async def get_preset_by_name(self, name: str) -> Optional[dict]:
        async with self.db.session() as session:
            result = await session.execute(
                select(Preset).where(Preset.name == name)
            )
            preset = result.scalar_one_or_none()
            return self._serialize(preset) if preset else None

    async def create_preset(
        self,
        name: str,
        boot_uris: dict,
        activate: bool = False,
    ) -> dict:
        from sqlalchemy.exc import IntegrityError
        async with self.db.session() as session:
            if activate:
                await session.execute(
                    update(Preset).values(is_active=False)
                )

            preset = Preset(
                name=name,
                boot_uris=json.dumps(boot_uris, ensure_ascii=False),
                is_active=activate,
            )
            session.add(preset)
            try:
                await session.flush()
            except IntegrityError:
                raise ValueError(f"Preset '{name}' already exists")
            return self._serialize(preset)

    async def update_preset(
        self,
        preset_id: int,
        **kwargs
    ) -> Optional[dict]:
        from sqlalchemy.exc import IntegrityError
        async with self.db.session() as session:
            preset = await session.get(Preset, preset_id)
            if not preset:
                return None

            if "name" in kwargs:
                preset.name = kwargs["name"]
            if "boot_uris" in kwargs:
                preset.boot_uris = json.dumps(kwargs["boot_uris"], ensure_ascii=False)

            preset.updated_at = datetime.now()
            try:
                await session.flush()
            except IntegrityError:
                raise ValueError(f"Preset '{preset.name}' already exists")
            return self._serialize(preset)

    async def delete_preset(self, preset_id: int) -> bool:
        async with self.db.session() as session:
            preset = await session.get(Preset, preset_id)
            if not preset:
                return False
            if preset.is_active:
                return False
            await session.delete(preset)
            return True

    async def activate_preset(self, preset_id: int) -> Optional[dict]:
        async with self.db.session() as session:
            preset = await session.get(Preset, preset_id)
            if not preset:
                return None

            await session.execute(
                update(Preset).values(is_active=False)
            )
            preset.is_active = True
            preset.updated_at = datetime.now()
            await session.flush()
            return self._serialize(preset)

    async def duplicate_preset(self, preset_id: int, new_name: str) -> Optional[dict]:
        from sqlalchemy.exc import IntegrityError
        async with self.db.session() as session:
            source = await session.get(Preset, preset_id)
            if not source:
                return None

            new_preset = Preset(
                name=new_name,
                boot_uris=source.boot_uris,
                path_masks=source.path_masks,
                is_active=False,
            )
            session.add(new_preset)
            try:
                await session.flush()
            except IntegrityError:
                raise ValueError(f"Preset '{new_name}' already exists")
            return self._serialize(new_preset)

    @staticmethod
    def _serialize(preset: Preset) -> dict:
        return {
            "id": preset.id,
            "name": preset.name,
            "boot_uris": json.loads(preset.boot_uris),
            "path_masks": json.loads(preset.path_masks) if preset.path_masks else None,
            "is_active": preset.is_active,
            "created_at": preset.created_at.isoformat() if preset.created_at else None,
            "updated_at": preset.updated_at.isoformat() if preset.updated_at else None,
        }
