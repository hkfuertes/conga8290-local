"""Local imported layout only; no polling, auth, uploads or cleaning."""
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import stat
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DOMAIN
from .map_render import MapData
from .map_cache_decoder import MAX_INPUT
from .hacs_v2_map_adapter import render_v2_map

_LOGGER = logging.getLogger(__name__)

def read_snapshot(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or not 24 <= info.st_size <= MAX_INPUT):
            raise ValueError("private_regular_snapshot_required")
        return render_v2_map(handle.read(MAX_INPUT + 1), MapData)

class VacuumMapCoordinator(DataUpdateCoordinator[MapData]):
    source_kind = "imported_history_snapshot"
    freshness_validated = False
    orientation_validated = False
    read_only = True

    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, config_entry=entry, name=entry.title,
                         update_interval=None, always_update=False)
        self._path = Path(hass.config.path(".cache", DOMAIN, "imported-layout.bin"))

    async def _async_update_data(self):
        try:
            return await self.hass.async_add_executor_job(read_snapshot, self._path)
        except Exception:
            raise UpdateFailed("Imported v2 snapshot unavailable or invalid") from None

    def close(self):
        pass

@dataclass
class VacuumMapRuntime:
    coordinator: VacuumMapCoordinator
    device_info: object
    tuya_local_object_id: str | None
    entity_id_prefix: str
