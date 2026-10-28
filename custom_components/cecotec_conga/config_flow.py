"""Config flow: Cecotec login -> robot discovery -> local_key recovered.

No files, no binary: the login runs the OEM cloud flow in-process and the
resulting session is stored in the config entry. The recovered local_key is
surfaced via a persistent notification so it can be pasted into tuya_local.
"""
import logging
import os
import re

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_COUNTRY, CONF_DEVICE_ID, CONF_DEV_ID, CONF_ECODE, CONF_EMAIL,
    CONF_HOST, CONF_LOCAL_KEY, CONF_PHONE_ID, CONF_SID, CONF_API_URL,
    CONF_GID, CONF_WAIT, DOMAIN, PRODUCT_ID,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_WAIT = 45


def _scan_tuyalocal_host() -> str:
    for cand in (
        os.path.join(os.getcwd(), "tuya_local.yaml"),
        "/config/tuya_local.yaml",
    ):
        try:
            with open(cand, encoding="utf-8") as fh:
                for line in fh:
                    m = re.match(r"\s*host:\s*([0-9.]+)\s*$", line)
                    if m:
                        return m.group(1)
        except OSError:
            continue
    return ""


class CongaMapConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input.get(CONF_HOST) or await self.hass.async_add_executor_job(
                _scan_tuyalocal_host
            )
            if not host:
                errors[CONF_HOST] = "host_required"
            if not errors:
                ok, data, err = await self.hass.async_add_executor_job(
                    _login_and_discover, user_input, host
                )
                if ok:
                    return self.async_create_entry(
                        title=f"Conga 8290 ({data[CONF_DEVICE_ID][-6:]})",
                        data={**user_input, CONF_HOST: host, **data},
                    )
                errors[err[0]] = err[1]
        defaults = user_input or {}
        scanned = defaults.get(CONF_HOST) or await self.hass.async_add_executor_job(
            _scan_tuyalocal_host
        )
        schema = vol.Schema({
            vol.Required(CONF_EMAIL, default=defaults.get(CONF_EMAIL, "")): str,
            vol.Required("password", default=defaults.get("password", "")): str,
            vol.Required(CONF_COUNTRY, default=defaults.get(CONF_COUNTRY, "34")): str,
            vol.Required(CONF_HOST, default=scanned): str,
            vol.Optional(CONF_WAIT, default=defaults.get(CONF_WAIT, DEFAULT_WAIT)): int,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return None


def _login_and_discover(form: dict, host: str):
    """Blocking: run OEM login + device discovery. Returns (ok, data, error)."""
    from .lib.cloud import OEMCloud

    try:
        cloud = OEMCloud()
        cloud.login(form[CONF_COUNTRY], form[CONF_EMAIL], form["password"])
        homes = cloud.homes() or []
        gid = None
        for home in homes:
            gid = home.get("groupId") or home.get("gid") or home.get("id")
            if gid:
                break
        if gid is None:
            return False, None, ("base", "no_home")
        robot = None
        for dev in cloud.devices(gid) or []:
            if dev.get("productId") == PRODUCT_ID:
                robot = dev
                break
        if robot is None:
            return False, None, ("base", "no_robot")
        local_key = robot.get("localKey") or robot.get("local_key")
        dev_id = robot.get("devId")
        if not local_key or not dev_id:
            return False, None, ("base", "no_robot")
        return True, {
            CONF_SID: cloud.sid,
            CONF_ECODE: cloud.ecode,
            CONF_API_URL: cloud.api_url,
            CONF_PHONE_ID: cloud.phone_id,
            CONF_GID: int(gid),
            CONF_DEV_ID: dev_id,
            CONF_DEVICE_ID: dev_id,          # same id on LAN for this OEM
            CONF_LOCAL_KEY: local_key,
        }, None
    except Exception as exc:  # noqa: BLE001 - surfaced to the form
        _LOGGER.warning("conga login failed: %s", exc)
        return False, None, ("base", "login_failed")
