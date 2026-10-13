# Conga 8290 maps: verified milestones

The existing Tuya Local vacuum/profile stays unchanged. **The read-only historical
map camera is installed and verified on HA 2026.10.1.**

## What now works

- Cecotec OEM account/storage reads without a Tuya IoT developer project.
- Signed download of a historical cleaning map from the owned robot's history.
- Offline decoding of the real v2 layout: seven rooms and a private PNG preview.
- Parsing of 4,880 path wire points, without assuming physical/image alignment.
- Conversion to the pinned cornguo fork's actual `MapData` camera payload.

The fixed live layout/path objects both reported HTTP 404 / `object_not_found`
(the safe category for `NoSuchKey` or `NotFound`). A stored-map
index was empty; the separate cleaning-history index contained usable previews.
One historical preview was successfully downloaded. This establishes the working
read-only download route, **not live map freshness or automatic refresh**.

## First camera milestone

[Experimental source](experimental/README.md) reuses cornguo's camera and Tuya Local
device association, with a bounded v2 renderer and imported historical snapshot.
Only the camera platform remains. There are no account credentials, cloud clients,
room commands, map-upload requests, polling or capability/parser patches.

The approved HA trial passed configuration checking and used one Core restart to
discover the new integration. `camera.conga_8290_map` loaded and served PNG bytes
identical to the privately downloaded layout. Only one camera entity was registered;
the existing 25 enabled robot entities remained valid, with no missing/unavailable
states. The working vacuum YAML was unchanged and the robot remained docked.

A dedicated `Conga map` dashboard at `/conga-map/map` contains a standard
picture-entity card; no custom card is required for this snapshot milestone. The
camera image and stored card were checked through official HA APIs. Browser
appearance/orientation still need user review.

HA 2026.10 keeps device records separate per config entry. The map and vacuum share
the same Tuya Local identifier, but do not share one registry device ID. Existing
vacuum/device records were not forced together or edited to bypass that behavior.

This remains experimental and is not a HACS release. No actual floor plan
or map file is shipped. Do not install the unmodified fork for this model: its map
parser and room commands are incompatible or unvalidated, and it requests uploads.

## Still separate

Orientation, bathroom-to-room-ID mapping, dock/path coordinate transforms,
continuous OEM credential/session lifecycle, automatic refresh and room/zone command
acceptance are unvalidated. Displaying a historical map does not enable “clean only
the bathroom.” The recovery command remains a one-off key-recovery tool; its auth
and ownership-LIST allowlists have not been broadened for map research.

Passwords, account responses, sessions, storage credentials, signed URLs and private
floor plans must never be committed. Research reads used temporary values in RAM;
the diagnostic sessions were explicitly stopped without server logout.
