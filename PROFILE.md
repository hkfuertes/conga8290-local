# Experimental extended Tuya Local profile

The profile defines **56 entities**: 25 enabled by default and 31 disabled by
default. It covers all **60 scalar datapoints** in the cached product schema;
the nine raw fields are deliberately excluded because their encodings are unknown.
This is not evidence that the robot implements every feature.

The original six entities retain their mappings and identifiers. They loaded in
HA and returned status, but **physical control writes remain untested**. The
expanded profile has passed offline tests and was loaded on the test HA instance:
56 registry entities, 25 enabled with valid read states and 31 disabled by the
integration. **No physical writes were performed during deployment.**
Replacing the YAML alone may require an HA restart/reload to discover entities.
Existing entity-registry preferences can override the defaults described here.

## Default additions

| Entity | DP | Notes |
| --- | --- | --- |
| Work mode | 41 | Vacuum only, mop only, vacuum and mop |
| Cleaning pattern | 105 | Automatic, thorough, scrubbing, edges, spiral, square spiral |
| Mopping intensity | 53 | Slow, normal, fast |
| Y-pattern mopping | 104 | Boolean setting |
| Carpet preference / suction boost | 44 / 45 | Adaptive, avoid, ignore / boolean |
| Resume interrupted cleaning | 27 | Boolean setting |
| Do not disturb | 25 | Enable flag; not a DND time window |
| Volume / sound | 26 / 108 | 0–100% / boolean |
| Mop installation | 40 | Read telemetry |
| Consumable remaining life | 17 / 19 / 21 / 23 | Side brush, main brush, filter, mop; **minutes**, not percentages |
| Lifetime cleaning area / count / time | 29 / 30 / 31 | Totals, not per-run history |
| Fault bitmap | 28 | Full integer; preserves simultaneous faults, no guessed fault strings |

Water flow (DP10), work mode, pattern, intensity and Y-mopping are separate
controls. Protocol spelling errors such as `acrubbing` are preserved on the wire.

## Disabled-by-default additions

These entities exist in the YAML but must be explicitly enabled in HA before use.
`hidden: true` is an entity-registry default, **not a permissions barrier**.

| Entity | DP | Reason for caution |
| --- | --- | --- |
| Operational mode | 4 | Zone, position and selected-room modes need raw payloads that are not implemented |
| Manual direction | 12 | Sends movement commands; stop/exit options do not provide a dead-man timeout |
| Map data request | 16 | Writes a request DP; not a map downloader, decoder or camera |
| Quick mapping | 109 | May start movement or change the stored map |
| Customized mode | 39 | Configuration dependencies unknown |
| Second cleaning pass candidate | 101 | Display name and `geofence_switch` wire code disagree |
| Cruise / fan during return candidate | 46 / 146 | Behavior not verified |
| Voice language / area units | 36 / 42 | Product-specific effects not verified |
| Child lock | 47 | Changes a protection setting |
| Dust collection frequency code / candidate | 37 / 38 | Numerical meanings and trigger-versus-setting behavior unknown |
| Charging dock type | 103 | Hardware configuration; do not change casually |
| Mop self-cleaning / drying candidates | 49 / 50 | Compatible dock hardware is not established |
| Mop self-cleaning area interval / strength | 51 / 52 | Same hardware caveat; interval uses m² |
| Dedicated deep / edge / spiral / square-spiral candidates | 142–145 | Overlap DP105; precedence and trigger semantics unknown |
| Game icon code | 106 | Raw enum labels retained; game behavior unknown |
| Reset map | 13 | **Potentially destructive**; not needed to download/display a map |
| Reset side brush / main brush / filter / mop life | 18 / 20 / 22 / 24 | Clears maintenance counters |
| Estimated area / game availability / message code | 43 / 120 / 128 | Diagnostic sensors; not control writes |

All extension DPs are optional. None uses `force: true`, polling commands,
automatic resets or write side effects. Absent DPs may yield unknown state;
enabling an entity is not proof that the robot supports it. Maintenance life,
faults and message reports are exposed only as telemetry even where the cached
schema labels them writable.

## Still not implemented

- Raw fields DP14/15/32/33/34/35/107/110/147: map/path data, command transport,
  native schedules, DND time window, information, voice, icons and scores.
- Map image generation, room/zone coordinates, exclusion editing and room commands.
- History download, native timer encoding and sustained offline-operation testing.

Do not write arbitrary base64/hex strings to raw fields. A selector for an
operational mode does not implement the corresponding navigation command.

## Maps: reuse candidate and current research

The preferred reuse candidate is the
[`cornguo/tuya-vacuum-maps`](https://github.com/cornguo/tuya-vacuum-maps) fork.
It reuses Tuya Local's device/cache/connection for status and commands, but its
**map downloader still uses Tuya OpenAPI**. Selecting Tuya Local does not supply
OpenAPI authentication or a working map. Its pinned dependency `tuya-vacuum==0.1.8`:

- Downloads maps through Tuya **OpenAPI**, requiring a Tuya IoT client ID/secret
  and device access. These are not the LAN `local_key` or Cecotec login credentials.
- Provides a separate `VacuumMap(layout_hex, path_hex).to_image()` renderer, which
  could be reused with files obtained through the Cecotec OEM session route.
- Supports some compressed map versions 0/1; version 2 and uncompressed layouts
  explicitly raise `NotImplementedError`. Conga 8290 is not on the tested list.

Separate local research decoded a real v2 phone-cache layout with seven rooms and
tested an isolated adapter for the fork's existing camera payload. A historical
cleaning map was then downloaded through the Cecotec OEM route without a Tuya IoT
project. Live objects are absent; the historical camera is verified on HA 2026.10.1,
but live refresh remains unvalidated.
See [MAPS.md](MAPS.md) and the source-only camera experiment. The OEM account probes
are not part of this recovery distribution.

Do not install the unmodified fork expecting plug-and-play 8290 support: it can
automatically request a new map upload, and its room-command format is not validated
for this model. The intended first adaptation is read-only, with uploads, room
commands, cloud-write fallback and capability monkey patches disabled.

Floor plans, signed URLs and storage credentials must never be committed or included
in shared logs. Map polling needs a separately agreed credential lifecycle and would
be a separate component, not an extension of the one-off key-recovery script.
