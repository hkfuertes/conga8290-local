"""Read-only historical snapshot adaptation; no cloud or robot commands."""
from homeassistant.const import Platform
import homeassistant.helpers.config_validation as cv
from .const import DOMAIN
from .coordinator import VacuumMapCoordinator, VacuumMapRuntime
from .entity import entity_id_prefix, map_device

PLATFORMS = [Platform.CAMERA]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

async def async_setup_entry(hass, entry):
    coordinator = VacuumMapCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    device_info, object_id = map_device(hass, entry)
    entry.runtime_data = VacuumMapRuntime(
        coordinator, device_info, object_id, entity_id_prefix(entry, object_id))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
