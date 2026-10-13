"""Home Assistant entity to display the map from a vacuum."""

from typing import Any

from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN, Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import VacuumMapCoordinator, VacuumMapRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add camera for passed config_entry in HA."""
    async_add_entities([VacuumMapCamera(config_entry.runtime_data)])


class VacuumMapCamera(CoordinatorEntity[VacuumMapCoordinator], Camera):
    """Home Assistant entity to display the map from a vacuum."""

    _attr_is_streaming = True

    def __init__(self, runtime: VacuumMapRuntime) -> None:
        """Initialize the camera."""
        super().__init__(runtime.coordinator)
        Camera.__init__(self)
        entry = runtime.coordinator.config_entry
        self._attr_name = entry.title
        # Kept from before the other entities existed, so existing cameras stay
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = runtime.device_info
        self.content_type = "image/png"
        # Named after the Tuya Local vacuum, e.g. vacuum.robot gives
        # camera.robot_map; otherwise Home Assistant derives it from the name.
        # Only a suggestion: Home Assistant keeps an existing entity id.
        if runtime.tuya_local_object_id:
            self.entity_id = f"{CAMERA_DOMAIN}.{runtime.tuya_local_object_id}_map"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of the image."""
        return self.coordinator.data.image

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the vacuum's position and the image's id, for the map card."""
        data = self.coordinator.data
        if data is None:
            return {}
        position = data.vacuum_position
        return {
            "vacuum_position": (
                [round(position[0], 4), round(position[1], 4)] if position else None
            ),
            "image_id": data.image_id,
            "source_kind": self.coordinator.source_kind,
            "read_only": True,
            "freshness_validated": False,
            "orientation_validated": False,
        }
