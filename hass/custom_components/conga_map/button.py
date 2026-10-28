"""'Clean selected rooms' button — runs `conga roomclean` (MOVES the robot)."""
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .switch import RoomSwitch

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CleanRoomsButton(hass, coord, entry)])


class CleanRoomsButton(ButtonEntity):
    _attr_name = "Clean selected rooms"
    _attr_icon = "mdi:play-circle"

    def __init__(self, hass, coord, entry: ConfigEntry) -> None:
        self._hass = hass
        self._coord = coord
        self._attr_unique_id = f"{DOMAIN}_clean_rooms"

    async def async_press(self) -> None:
        entities = self._hass.states.async_all("switch")
        ids = []
        for state in entities:
            if state.attributes.get("friendly_name", "").startswith("Room ") and state.state == "on":
                # unique_id conga_map_room_<n>
                ent = state.entity_id
                try:
                    room = int(ent.rsplit("_", 1)[-1])
                    ids.append(room)
                except ValueError:
                    continue
        if not ids:
            _LOGGER.warning("clean_rooms pressed but no rooms selected")
            return
        _LOGGER.info("cleaning rooms %s (this moves the robot)", ids)
        args = ["roomclean"] + [str(i) for i in ids] + ["-passes", "1"]
        await self._hass.async_add_executor_job(self._coord.run, args)
