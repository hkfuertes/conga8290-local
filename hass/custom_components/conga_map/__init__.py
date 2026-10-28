"""Conga 8290 map integration — thin wrapper around the `conga` binary.

Map pipeline (robot -> cloud history -> S3 -> local PNG) and room commands
run in the single static binary; this integration only orchestrates it and
exposes camera/switches to Home Assistant. LAN credentials come from the
tuya_local YAML already present in the HA config directory.
"""
import asyncio
import json
import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, CONF_BINARY, CONF_CONFIG, CONF_TUYA_LOCAL, CONF_OUTDIR, CONF_WAIT
from .coordinator import CongaMapCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["camera", "switch", "button"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    opts = {
        CONF_BINARY: entry.data.get(CONF_BINARY, "/config/conga"),
        CONF_CONFIG: entry.data.get(CONF_CONFIG, "/config/conga-config.json"),
        CONF_TUYA_LOCAL: entry.data.get(CONF_TUYA_LOCAL, "/config/tuya_local.yaml"),
        CONF_OUTDIR: entry.data.get(CONF_OUTDIR, "/config/conga_maps"),
        CONF_WAIT: entry.data.get(CONF_WAIT, 45),
    }
    coord = CongaMapCoordinator(hass, opts)
    hass.data[DOMAIN][entry.entry_id] = coord

    def run(*args, json_out=False):
        return coord.run(args, json_out=json_out)

    hass.services.async_register(DOMAIN, "refresh_map",
        lambda call: hass.async_create_task(coord.async_refresh_map()))
    hass.services.async_register(DOMAIN, "roomclean",
        lambda call: hass.async_create_task(_roomclean(coord, call)))

    await hass.config_entries.async_forward_platforms(entry, PLATFORMS)
    # first map in the background so HA startup is not blocked ~60s
    hass.async_create_task(coord.async_refresh_map())
    return True


async def _roomclean(coord: CongaMapCoordinator, call: ServiceCall) -> None:
    rooms = call.data.get("rooms") or []
    passes = int(call.data.get("passes", 1))
    if not rooms:
        return
    args = ["roomclean"] + [str(r) for r in rooms] + ["-passes", str(passes)]
    await coord.hass.async_add_executor_job(coord.run, args)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
