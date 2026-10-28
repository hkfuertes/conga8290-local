"""Map camera: serves the latest PNG produced by `conga getmap`."""
import logging
import os

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CongaMapCamera(coord)])


class CongaMapCamera(Camera):
    _attr_name = "Conga map"

    def __init__(self, coord) -> None:
        super().__init__()
        self._coord = coord
        self._attr_unique_id = f"{DOMAIN}_map"

    @property
    def extra_state_attributes(self):
        return self._coord.latest or {}

    async def async_camera_image(self, width=None, height=None) -> bytes | None:
        path = self._coord.png_path()
        if not path or not os.path.exists(path):
            return None
        return await self.hass.async_add_executor_job(
            lambda: open(path, "rb").read()
        )
