"""Runs the conga binary and keeps the latest map JSON."""
import asyncio
import json
import logging
import os
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import CONF_BINARY, CONF_CONFIG, CONF_TUYA_LOCAL, CONF_OUTDIR, CONF_WAIT

_LOGGER = logging.getLogger(__name__)


class CongaMapCoordinator:
    def __init__(self, hass: HomeAssistant, opts: dict) -> None:
        self.hass = hass
        self.opts = opts
        self.latest: dict[str, Any] = {}   # conga getmap --json output
        self.listeners: list = []

    def run(self, args: list[str], json_out: bool = False) -> Optional[dict]:
        """Blocking subprocess call with config env (executor context)."""
        import subprocess

        env = dict(os.environ, CONGA_CONFIG=self.opts[CONF_CONFIG])
        cmd = [self.opts[CONF_BINARY]] + args
        if json_out and "getmap" in args:
            cmd += ["-json"]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"conga {' '.join(args)}: {proc.stderr.strip()}")
        return proc.stdout

    async def async_refresh_map(self) -> None:
        args = ["getmap", "-wait", str(self.opts[CONF_WAIT]), "-out", self.opts[CONF_OUTDIR]]
        await self.hass.async_add_executor_job(self._ensure_config)
        out = await self.hass.async_add_executor_job(self.run, args)
        data = self._parse_json(out)
        if data:
            self.latest = data
            for cb in list(self.listeners):
                cb()
        else:
            raise RuntimeError("conga getmap: no JSON in output")

    def _ensure_config(self) -> None:
        """One-time: import lan creds from tuya_local if the config lacks them."""
        cfg = self.opts[CONF_CONFIG]
        if not os.path.exists(cfg) or '"ip": ""' in open(cfg).read():
            if os.path.exists(self.opts[CONF_TUYA_LOCAL]):
                try:
                    self.run(["initlan", "-from-tuyalocal", self.opts[CONF_TUYA_LOCAL]])
                except Exception as exc:  # config may already be complete
                    _LOGGER.debug("initlan skipped: %s", exc)

    def _parse_json(self, out: str) -> Optional[dict]:
        start = out.find("{")
        if start < 0:
            return None
        try:
            return json.loads(out[start:])
        except json.JSONDecodeError:
            return None

    def png_path(self) -> Optional[str]:
        return self.latest.get("png_file")

    def rooms(self) -> list[dict]:
        return self.latest.get("rooms", [])
