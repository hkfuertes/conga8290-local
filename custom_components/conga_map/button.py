"""Buttons: clean selected rooms (moves robot) + reinstall tuya_local template."""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CongaMapCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CleanRoomsButton(hass, coord), ReinstallTemplateButton(coord)])


class CleanRoomsButton(ButtonEntity):
    _attr_name = "Clean selected rooms"
    _attr_icon = "mdi:play-circle"

    def __init__(self, hass, coord) -> None:
        self._hass = hass
        self._coord = coord
        self._attr_unique_id = f"{DOMAIN}_clean_rooms"

    async def async_press(self) -> None:
        ids = []
        for state in self._hass.states.async_all("switch"):
            if f"{DOMAIN}_room_" in state.entity_id and state.state == "on":
                try:
                    ids.append(int(state.entity_id.rsplit("_", 1)[-1]))
                except ValueError:
                    continue
        if not ids:
            _LOGGER.warning("clean_rooms pressed but no rooms selected")
            return
        _LOGGER.warning("cleaning rooms %s (this MOVES the robot)", ids)
        await self._hass.async_add_executor_job(self._coord.roomclean, ids, 1)


class ReinstallTemplateButton(ButtonEntity):
    """tuya_local wipes its devices/ dir on every update: one click restores it."""

    _attr_name = "Reinstall tuya_local template"
    _attr_icon = "mdi:file-restore"

    def __init__(self, coord) -> None:
        self._coord = coord
        self._attr_unique_id = f"{DOMAIN}_reinstall_template"

    async def async_press(self) -> None:
        from homeassistant.components import persistent_notification

        dst = await self._coord.hass.async_add_executor_job(
            self._coord.install_tuya_local_profile
        )
        persistent_notification.async_create(
            self._coord.hass,
            title="tuya_local template reinstalled",
            message=dst,
            notification_id=f"{DOMAIN}_template",
        )
