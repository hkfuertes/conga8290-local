"""Config flow: paths only. The binary does the real provisioning
(extract/login/initlan) outside HA or via the CLI service."""
import os

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_BINARY, CONF_CONFIG, CONF_TUYA_LOCAL, CONF_OUTDIR, CONF_WAIT, DOMAIN,
)

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_BINARY, default="/config/conga"): str,
    vol.Required(CONF_CONFIG, default="/config/conga-config.json"): str,
    vol.Required(CONF_TUYA_LOCAL, default="/config/tuya_local.yaml"): str,
    vol.Required(CONF_OUTDIR, default="/config/conga_maps"): str,
    vol.Optional(CONF_WAIT, default=45): int,
})


class CongaMapConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            if not os.path.exists(user_input[CONF_BINARY]):
                errors[CONF_BINARY] = "binary_missing"
            if not errors:
                return self.async_create_entry(title="Conga 8290 map", data=user_input)
        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return None
