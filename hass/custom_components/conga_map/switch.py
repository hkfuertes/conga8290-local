"""Per-room selection switches (cornguo-style) fed by conga getmap rooms."""
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    rooms_switches = [RoomSwitch(coord, r) for r in coord.rooms()]
    async_add_entities(rooms_switches)

    @callback
    def _refresh():
        have = {s.room_id for s in rooms_switches}
        new = [RoomSwitch(coord, r) for r in coord.rooms() if r["ID"] not in have]
        if new:
            async_add_entities(new)

    coord.listeners.append(_refresh)


class RoomSwitch(SwitchEntity):
    """Toggle = mark room for the next 'clean selected' button press."""

    def __init__(self, coord, room: dict) -> None:
        self._coord = coord
        self.room_id = room["ID"]
        self._attr_name = f"Room {room['Name']}"
        self._attr_unique_id = f"{DOMAIN}_room_{self.room_id}"
        self._on = False
        self._extra = dict(room)

    @property
    def is_on(self) -> bool:
        return self._on

    @property
    def extra_state_attributes(self):
        return self._extra

    def turn_on(self, **kwargs):
        self._on = True
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        self._on = False
        self.schedule_update_ha_state()

    @property
    def available(self) -> bool:
        return any(r["ID"] == self.room_id for r in self._coord.rooms())

    @callback
    def clear(self):
        self._on = False
        self.schedule_update_ha_state()
