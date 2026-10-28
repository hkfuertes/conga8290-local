"""Conga 8290 map integration — pure Python, no external binary.

Login (config flow) recovers local_key from the Cecotec cloud; the map
pipeline (LAN get_both -> S3 history -> decode -> PNG) and room commands
(V1 0x14 frames via DP15) run in-process. tuya_local keeps doing the
day-to-day robot control.
"""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.typing import ConfigType

from .const import ATTR_PASSES, ATTR_ROOMS, CONF_LOCAL_KEY, DOMAIN
from .coordinator import CongaMapCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["camera", "switch", "button"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coord = CongaMapCoordinator(hass, dict(entry.data))
    hass.data[DOMAIN][entry.entry_id] = coord

    async def refresh_map(call: ServiceCall) -> None:
        await coord.async_refresh_map()

    async def roomclean(call: ServiceCall) -> None:
        # accept [3,5] or [{room:3},{room:5}] (xiaomi-card [[variables]] form)
        raw = call.data.get(ATTR_ROOMS) or []
        ids = [int(r["room"] if isinstance(r, dict) else r) for r in raw]
        passes = int(call.data.get(ATTR_PASSES, 1))
        if ids:
            _LOGGER.warning("roomclean %s x%d: robot will MOVE", ids, passes)
            await hass.async_add_executor_job(coord.roomclean, ids, passes)

    async def install_template(call: ServiceCall) -> None:
        dst = await hass.async_add_executor_job(coord.install_tuya_local_profile)
        _notify(hass, "tuya_local template installed", dst)

    hass.services.async_register(DOMAIN, "refresh_map", refresh_map)
    hass.services.async_register(DOMAIN, "roomclean", roomclean)
    hass.services.async_register(DOMAIN, "install_template", install_template)

    _notify(hass, "Conga: local_key recovered",
            f"local_key: {entry.data[CONF_LOCAL_KEY]}\n"
            "Paste it into tuya_local if it is not configured yet.")

    await hass.config_entries.async_forward_platforms(entry, PLATFORMS)
    # first map in background: HA startup must not block ~60 s
    hass.async_create_task(coord.async_refresh_map())
    return True


def _notify(hass: HomeAssistant, title: str, message: str) -> None:
    from homeassistant.components import persistent_notification

    persistent_notification.async_create(
        hass, title=title, message=message, notification_id=f"{DOMAIN}_setup"
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
