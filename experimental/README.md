# Experimental read-only map camera

`read_only_maps/custom_components/tuya_vacuum_maps/` is a source-only adaptation
of [cornguo/tuya-vacuum-maps](https://github.com/cornguo/tuya-vacuum-maps) at
`2a90f18a0bacd1451599a3f679d6e6f524b82dcb`. The original camera and Tuya Local
device association are reused, and the upstream MIT license is retained.

**Installed and verified on Home Assistant 2026.10.1**, after an approved config
check and one Core restart. The camera image matched the private imported layout,
and a standard picture-entity dashboard card was saved. It is not a
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

HA 2026.10 uses separate device records per config entry. The original camera's
Tuya Local identifier is retained, but the camera and vacuum have separate registry
device IDs; the original vacuum and its 25 enabled entities remain unchanged.

The config entry saves only the selected device ID. No map, account response,
session, storage credential or signed URL is included in this repository.

Offline tests cover the source/import boundary, exact public camera payload,
synthetic v2 decoding, privacy checks and PNG rendering. They are **not** HA runtime
tests. The separate HA trial also verified the actual camera PNG and saved dashboard
card. User review of browser rendering/orientation is still needed. Continuous
cloud retrieval still needs an agreed credential lifecycle.

## Manual setup on another HA instance

1. Do not proceed if `custom_components/tuya_vacuum_maps` is already installed.
   Back up HA first; this experiment is not an in-place upgrade of another fork.
2. Copy the supplied `custom_components/tuya_vacuum_maps` folder into HA's
   `/config/custom_components/`. No cloud credentials or pip packages are needed.
3. Separately import your own decoded v2 `layout.bin` as
   `/config/.cache/tuya_vacuum_maps/imported-layout.bin`, owned by the HA process,
   mode `0600`. Never put private map files in this repository.
4. Check HA configuration, then restart Core at an explicitly approved time.
5. Add **Tuya Vacuum Maps (read-only historical snapshot)** under Devices & Services
   and select the already configured Tuya Local vacuum. Only one map entry is allowed.
6. Add the standard card from [dashboard.yaml](read_only_maps/dashboard.yaml), changing
   its camera entity if necessary. No Xiaomi/custom map card is needed for this stage.

The imported file is a snapshot: it does not update when the robot cleans. The
camera must not be represented as a live map or used to infer valid room commands.
