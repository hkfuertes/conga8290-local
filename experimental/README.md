# Experimental read-only map camera

`read_only_maps/custom_components/tuya_vacuum_maps/` is a source-only adaptation
of [cornguo/tuya-vacuum-maps](https://github.com/cornguo/tuya-vacuum-maps) at
`2a90f18a0bacd1451599a3f679d6e6f524b82dcb`. The original camera and Tuya Local
device association are reused, and the upstream MIT license is retained.

**This has not been installed or runtime-tested in Home Assistant.** It is not a
HACS release, live cloud downloader or room-cleaning implementation. Do not
overwrite an existing integration using the same domain.

## Deliberately limited behavior

- Only one camera platform; no buttons, switches, passes, room services or cards.
- Reads a separately imported v2 historical layout from the fixed path
  `.cache/tuya_vacuum_maps/imported-layout.bin` under the HA config directory.
- Requires a regular, non-symlink file owned by the HA process with mode `0600`.
- Selects an existing Tuya Local device and associates its camera by identifier.
  It does not open another LAN connection or read/write datapoints.
- No account credentials, network clients, automatic polling, map-upload requests,
  font downloads, parser/capability monkey patches or cloud fallback.
- Labels the source as `imported_history_snapshot`; orientation and freshness
  remain unvalidated. No path, robot, dock or virtual areas are overlaid.

The config entry saves only the selected device ID. No map, account response,
session, storage credential or signed URL is included in this repository.

Offline tests cover the source/import boundary, exact public camera payload,
synthetic v2 decoding, privacy checks and PNG rendering. They are **not** HA runtime
tests. An approved HA trial, including any required restart, is the next separate
milestone. Continuous cloud retrieval still needs an agreed credential lifecycle.
