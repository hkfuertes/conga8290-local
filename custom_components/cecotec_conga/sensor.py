"""Diagnostic sensor exposing the recovered Tuya local_key."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory

from .const import DOMAIN, device_info


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coord = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LocalKeySensor(coord)])


class LocalKeySensor(SensorEntity):
    """Shows the local_key recovered by the config-flow login (for tuya_local)."""

    _attr_icon = "mdi:key-variant"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord) -> None:
        self._coord = coord
        self._attr_name = "Conga local key"
        self._attr_unique_id = f"{DOMAIN}_local_key"
        self._attr_device_info = device_info(coord.dev_id)

    @property
    def native_value(self) -> str | None:
        return self._coord.lan_cfg.get("local_key")
