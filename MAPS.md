# Conga 8290 maps: verified milestones

The existing Tuya Local vacuum/profile stays unchanged. **No map camera has been
installed or validated in HA yet.**

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

This is source-only, tested offline, and not a HACS release. An approved HA trial is
still needed, and a full restart must be approved separately. No actual floor plan
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
