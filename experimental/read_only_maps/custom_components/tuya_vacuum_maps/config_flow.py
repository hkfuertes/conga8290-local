"""Select an existing Tuya Local vacuum; never request account credentials."""
import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, TUYA_LOCAL_DOMAIN
from .coordinator import read_snapshot
from pathlib import Path

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        entries = {entry.entry_id: entry for entry in
                   self.hass.config_entries.async_entries(TUYA_LOCAL_DOMAIN)}
        errors = {}
        if not entries:
            return self.async_abort(reason="no_tuya_local")
        if user_input is not None:
            entry = entries.get(user_input.get("tuya_local_entry"))
            if entry is None:
                errors["base"] = "invalid_selection"
            else:
                data = {**entry.data, **entry.options}
                device_id = data.get("device_cid") or data.get("device_id")
                if not isinstance(device_id, str) or not device_id:
                    errors["base"] = "invalid_selection"
                else:
                    await self.async_set_unique_id(device_id)
                    self._abort_if_unique_id_configured()
                    try:
                        path = Path(self.hass.config.path(".cache", DOMAIN, "imported-layout.bin"))
                        await self.hass.async_add_executor_job(read_snapshot, path)
                    except Exception:
                        errors["base"] = "snapshot_invalid"
                    else:
                        return self.async_create_entry(title=f"{entry.title} historical map",
                                                      data={"device_id": device_id})
        return self.async_show_form(step_id="user", errors=errors, data_schema=vol.Schema({
            vol.Required("tuya_local_entry"): vol.In({key: entry.title for key, entry in entries.items()})}))
