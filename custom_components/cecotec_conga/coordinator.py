"""Coordinator: map pipeline + room commands, all in-process (no subprocess).

getmap: LAN get_both trigger -> wait for cloud upload -> S3 history download
-> decode (lib.mapfile) -> render PNG. Room clean: proven V1 0x14 frame via
DP15 over a short-lived LAN connection.
"""
import base64
import logging
import time
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICE_ID, CONF_DEV_ID, CONF_ECODE, CONF_GID, CONF_HOST,
    CONF_LOCAL_KEY, CONF_PHONE_ID, CONF_SID, CONF_WAIT,
)

_LOGGER = logging.getLogger(__name__)


class CongaMapCoordinator:
    def __init__(self, hass: HomeAssistant, entry_data: dict) -> None:
        self.hass = hass
        self.wait = int(entry_data.get(CONF_WAIT, 45))
        self.lan_cfg = {
            "device_id": entry_data[CONF_DEVICE_ID],
            "host": entry_data[CONF_HOST],
            "local_key": entry_data[CONF_LOCAL_KEY],
        }
        self.session = {
            "sid": entry_data[CONF_SID],
            "ecode": entry_data[CONF_ECODE],
            "api_url": entry_data.get("api_url", "a1.tuyaeu.com"),
            "phone_id": entry_data.get(CONF_PHONE_ID),
        }
        self.gid = entry_data[CONF_GID]
        self.dev_id = entry_data[CONF_DEV_ID]
        self.latest: dict[str, Any] = {}
        self.png: bytes | None = None
        self.listeners: list = []
        self.map_dir = Path(hass.config.path("conga_maps"))
        self.map_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ cloud
    def _cloud(self):
        from .lib.cloud import OEMCloud
        cloud = OEMCloud(self.session["phone_id"])
        cloud.sid = self.session["sid"]
        cloud.ecode = self.session["ecode"]
        return cloud

    # ------------------------------------------------------------------ map
    async def async_refresh_map(self) -> None:
        await self.hass.async_add_executor_job(self._refresh)
        for cb in list(self.listeners):
            cb()

    def _refresh(self) -> None:
        from .lib.lan import CongaLAN
        from .lib.s3map import download_map
        from .lib.mapfile import decode_bytes
        from .lib.render import render_png

        try:  # best-effort: robot may be busy; newest cloud map still lists
            CongaLAN(**self.lan_cfg).trigger_get_both()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("get_both trigger failed (%s); downloading latest", exc)
        time.sleep(self.wait)

        from .lib.s3map import download_map
        from .lib.mapfile import decode_bytes
        from .lib.render import render_png

        entry, raw = download_map(self._cloud(), self.dev_id, self.gid)
        decoded = decode_bytes(raw)
        decoded["map_file"] = entry.get("file", "")
        stamp = time.strftime("%Y%m%d_%H%M%S")
        png_path = str(self.map_dir / f"map_{stamp}.png")
        render_png(raw, png_path)
        self.png = Path(png_path).read_bytes()
        (self.map_dir / "map.png").write_bytes(self.png)
        _LOGGER.info("map %s decoded: %d rooms", decoded.get("map_id"),
                     len(decoded.get("rooms", [])))
        self.latest = decoded

    # -------------------------------------------------------------- commands
    def roomclean(self, room_ids: list[int], passes: int = 1) -> None:
        """Send the proven 0x14 room-clean frame via DP15 (MOVES THE ROBOT)."""
        from .lib.lan import CongaLAN

        payload = bytes([0x14, passes & 0xFF, len(room_ids), *room_ids])
        frame = bytes([0xAA, 0x01]) + len(payload).to_bytes(4, "big") + payload
        frame += bytes([sum(payload) & 0xFF])
        resp = CongaLAN(**self.lan_cfg).send_dps(
            {"15": base64.b64encode(frame).decode()}
        )
        _LOGGER.info("roomclean %s x%d sent (moves robot): %s",
                     room_ids, passes, resp or "sent")

    def install_tuya_local_profile(self) -> str:
        """Re-copy the embedded device YAML into tuya_local's devices dir."""
        import shutil
        src = Path(__file__).parent / "tuya_local_profile.yaml"
        dst_dir = Path(self.hass.config.path(
            "custom_components/tuya_local/devices"))
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        shutil.copyfile(src, dst)
        return str(dst)

    # ----------------------------------------------------------------- utils
    def rooms(self) -> list[dict]:
        return self.latest.get("rooms", [])
