"""Base entity and device for Tuya Vacuum Maps."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN, TUYA_LOCAL_DOMAIN
from .coordinator import VacuumMapCoordinator, VacuumMapRuntime


def map_device(hass: HomeAssistant, entry: ConfigEntry) -> tuple[DeviceInfo, str | None]:
    """Return the entry's device and the object id of its Tuya Local vacuum.

    Entities go on the vacuum's Tuya Local device if there is one, linked only
    by identifier so its name and other details are left unchanged. Their
    entity ids then start with the Tuya Local vacuum's, e.g. vacuum.robot gives
    switch.robot_room_0.
    """
    device_id = entry.data["device_id"]
    tuya_local_identifier = (TUYA_LOCAL_DOMAIN, device_id)
    tuya_local_device = dr.async_get(hass).async_get_device(
        identifiers={tuya_local_identifier}
    )
    if not tuya_local_device:
        return DeviceInfo(identifiers={(DOMAIN, device_id)}, name=entry.title), None

    device_info = DeviceInfo(identifiers={tuya_local_identifier})
    for entity in er.async_entries_for_device(er.async_get(hass), tuya_local_device.id):
        if entity.platform == TUYA_LOCAL_DOMAIN and entity.domain == "vacuum":
            return device_info, split_entity_id(entity.entity_id)[1]
    return device_info, None


def entity_id_prefix(entry: ConfigEntry, tuya_local_object_id: str | None) -> str:
    """Return the object id the entry's entity ids start with."""
    return tuya_local_object_id or slugify(entry.title)


class VacuumMapEntity(CoordinatorEntity[VacuumMapCoordinator]):
    """An entity of a Tuya Vacuum Maps entry."""

    # Whether the entity stays available when a map update fails, using the
    # last map. Rooms rarely change, and room commands may not need the cloud
    # (Tuya Local), so room selection and cleaning keep working.
    _available_with_last_map = False

    def __init__(self, runtime: VacuumMapRuntime, platform: str, key: str) -> None:
        """Initialize the entity.

        @param key: Unique within the entry, e.g. "room_0".
        """
        super().__init__(runtime.coordinator)
        self._runtime = runtime
        self._attr_unique_id = f"{runtime.coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = runtime.device_info
        # Only a suggestion: Home Assistant keeps an existing entity id
        self.entity_id = f"{platform}.{runtime.entity_id_prefix}_{key}"

    @property
    def available(self) -> bool:
        """Return whether the entity can be used."""
        if self._available_with_last_map:
            return self.coordinator.data is not None
        return super().available
