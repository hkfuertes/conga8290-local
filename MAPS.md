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

## Python room inspection

`inspect_map.py` now decodes an existing private v2 layout entirely offline:

```sh
python3 inspect_map.py --input /private/path/map.bin.stream \
  --output-dir /private/path/new-room-report --source-kind phone_cache
```

Choose `phone_cache`, `history_snapshot` or `user_file` only to describe the input;
this option does not verify its provenance/freshness. Input must be an owned regular
non-symlink `0600` file. Outputs are a new `0700` directory with `0600` JSON, PNG and
a self-contained SVG labeling the numeric room IDs. No account/APK/phone/HA setup
or additional Python packages are needed for this offline command.

Validation: 95 distribution tests passed, alongside 320 root research-tool tests.
The private trial's SVG labels/embedded PNG and output permissions were checked;
these checks do not validate orientation, square metres or independent download.

The room report includes ID/name, floor+carpet cell count, carpet count, grid bounds,
raw cleaning-option fields and optional unsigned polygon wire vertices. Raw header
resolution/origin/dock values are preserved without guessing physical units. Raster
hex keys differ from numeric room IDs: ID3 corresponds to floor byte `1f`, **not**
command ID31. Pixel counts are not measured m², cleanable surface or guaranteed
cleaning-command IDs; `area_m2` remains null and command validation false.
Optional polygon panel coordinates use the source-proven signed-like/10/Y-flip
transform; they are not declared physical or grid coordinates. Polygons may be
absent even when the raster contains a complete segmented room.

A separately scoped research-only read of the connected phone's exact map cache
successfully decoded seven rooms and generated private reports without taps,
logins, captures or robot commands. The cache reader is not included in the public
CLI: it requires already-available phone access and does not refresh/download from
the robot. No private floor plan, room report or actual household area is shipped.

## Retrieval and controls remain separate

A later explicitly authorized trial sent one DP16 `get_both` request through the
existing Tuya Local connection, without starting cleaning. The fixed live objects
still returned 404 afterward. The temporary trial service was removed; the camera
and dashboard remain historical, with the original vacuum profile unchanged.

Static panel/SDK analysis identified a separate P2P file-transfer route. A passive
phone-cache read decoded a different layout from the displayed history, but matched
the earlier phone cache: this is not proof of freshness or independent retrieval.
A standalone Python P2P map downloader is not yet validated. Camera-oriented P2P
clients must not be used unchanged: their automatic video controls have unknown
effects on this robot. No upload service or P2P client is included in this source.

Further phone-assisted research observed a direct UDP conversation with the robot
while its map/path cache modification times advanced. One source-backed OEM RTC
configuration read also succeeded without a developer project. The authentication
and album-index framing now have synthetic Python tests, but negotiation, selected
cipher/key selection and independent map retrieval remain unresolved. Packet
metadata and cache timestamps do not prove new floor-plan content. HA was not
changed by this follow-up, and no cleaning command was invoked by the tools.

The next static/offline pass resolved built-in cipher definitions, conditional
session-key decoding, HMAC-SHA1 packet tags, channel-to-KCP mapping and map-file
stream layouts. Synthetic Python tests cover a map-only request and a complete
in-memory decode pipeline. Actual session selection/negotiation, relay handshake,
authentication acknowledgement and robot acceptance remain unverified. No new
login, robot connection or HA change was performed in that pass; its research
helpers are not distributed as a working P2P client.

Local retrieval remains the priority. Further APK/native analysis established a
direct UDP data path and LAN signaling command 32, with local-key encryption and
ordinary Tuya-style outgoing framing. Opening an accepted map session using only
device ID/local key is still unproven: the examined app also obtains cloud-backed
authentication material. Bounded passive observations during map-view reopening
did not identify a map-data transfer. Neither these observations nor the static
codec evidence establishes independent retrieval, freshness or Internet-free setup.
The historical HA camera and vacuum configuration remain unchanged.

[WebWire-NL/cecotec](https://github.com/WebWire-NL/cecotec) is a useful related
Tuya Local reference for the Conga 11090. Its "DP map" documents datapoints, not
floor-plan retrieval; it contains no P2P map downloader. Do not replace the 8290
profile with its different model's YAML or follow its re-pairing advice: this
project already recovers the local key while preserving Cecotec pairing.

Orientation, bathroom-to-room-ID mapping, dock/path coordinate transforms,
continuous OEM credential/session lifecycle, automatic refresh and room/zone command
acceptance are unvalidated. Displaying a historical map does not enable “clean only
the bathroom.” The recovery command remains a one-off key-recovery tool; its auth
and ownership-LIST allowlists have not been broadened for map research.

Passwords, account responses, sessions, storage credentials, signed URLs and private
floor plans must never be committed. Research reads used temporary values in RAM;
the diagnostic sessions were explicitly stopped without server logout.
