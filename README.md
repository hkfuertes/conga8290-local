# Conga 8290 → Tuya Local

Two outputs: a **Tuya Local YAML profile** and the robot's **ID + local_key**.
One-off recovery using Python, without Android/root, Frida or a Tuya IoT project.
After setup, Home Assistant uses Tuya Local to communicate over LAN, protocol **3.3**.

## Requirements

- Targets: **macOS, Linux or Linux Docker**, Python **3.12/3.13** and dependencies.
- **Linux amd64/x86_64 is supported**: Unicorn emulates the APK's ARM64 libraries;
  an ARM processor is not required. Windows is out of scope.
- A Cecotec app account with email/password and Internet access for recovery.
- A compatible Cecotec **1.2.9** XAPK, supplied locally. This tool accepts only
  the APK and libraries whose hashes are pinned in the source code.
- Tuya Local installed in Home Assistant to use the YAML profile.

The APK/XAPK and proprietary libraries **are not distributed in this repository**.
The importer extracts only the three required resources, verifies their SHA-256
hashes and stores them in `artifacts/`, which Git ignores. It never uploads the APK
or runs it on Android; selected ARM64 routines are emulated locally with bounded
execution in Unicorn. Do not use an arbitrary version: mismatched resources fail closed.

### Download the compatible version

[Cecotec 1.2.9 on APKPure](https://apkpure.com/cecotec/es.cecotec.forceclima/download/1.2.9)

- Package: `es.cecotec.forceclima`, version **1.2.9 (versionCode 32)**.
- Choose **XAPK `arm64-v8a`**, approximately **140.4 MB**, not `armeabi-v7a`.
  This is the architecture of the emulated libraries, not the host computer:
  this variant is also required for Linux/Docker amd64 and Mac.
- The XAPK must contain `es.cecotec.forceclima.apk` and `config.arm64_v8a.apk`.
- SHA-256 of the **complete XAPK** used in testing (matches the hash published
  on the page when checked):
  `a9862e4f1626b58a832782e58d9843f86c20d30934d7a63eebdfa872b55815e5`.
- SHA-256 of the **internal base APK**, different from the XAPK container hash:
  `ed4356d58095a2a7cc542d34941c0040ca24ce77b90aafee3234732e9e65d3ef`.

The importer verifies the base APK and both internal libraries by their hashes,
not just the name/version or container hash. Download the XAPK locally and supply
its path with `--xapk`; no phone installation or APKPure app is required.

## Install and prepare

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python recover_key.py --xapk /path/to/Cecotec_1.2.9_APKPure.xapk --check
```

This check is offline: it does not request account details or log in. Import is
only required once; it does not replace existing files that do not match.

## Recover ID + key

```sh
.venv/bin/python recover_key.py
```

Country calling code (default: Spain, 34) and email are **visible**. Password input
shows **asterisks**, without echoing or storing the password. There is no confirmation
phrase or additional approval flag: **running this command performs a new login**.
It may trigger an unknown-device alert or affect an existing Cecotec app session.

The script lets you select a home and a Conga 8290 from the account's devices.
A single matching item is selected automatically. No previous capture or knowledge
of the robot's ID/key is required. Other products are not accepted just because
their names look similar. It makes one token request, one login and **at most two
LISTs**, with no retries, logout, pairing or robot commands. CAPTCHA/MFA/account
restrictions stop the process.

Only the selected device is saved, in a new file:

```text
private/robot-connection-<timestamp>.json
```

Fields: `id` and `local_key`. File mode **0600**, directory mode **0700**. On success,
the script also **prints the ID and key to the console** as a JSON block on stderr;
stdout retains the status summary. It does not print passwords, tokens, RSA values,
sessions or full account responses. The email may remain visible after the prompt.
**Do not share screenshots/logs of this output or the private JSON**, even in a
private repository. In Docker, keep `--log-driver none`, as shown in the examples.

### Account arguments (optional)

```sh
.venv/bin/python recover_key.py -c 34 -u user@example.com
# Supported, but less secure; replace the values locally:
.venv/bin/python recover_key.py -c 34 -u user@example.com -p 'PASSWORD'
```

Long aliases: `--country`, `--user` and `--password`. `-c` is a telephone calling
code without `+` or `00`, not an ISO country code. Missing arguments are prompted
locally. **`-p` exposes the password in shell history and process arguments; in
Docker, it also appears in container metadata**. The script does not print or store
these account values, but cannot hide them from the operating system. Prefer `-c`/`-u`
with the masked password prompt. Account arguments are rejected with `--check`,
and passwords are rejected with `--token-only`. Multiple homes/robots require
interactive selection even when all credentials are supplied.

To check token/RSA only, without a password or login:

```sh
.venv/bin/python recover_key.py --token-only
```

## Docker (Linux amd64, also usable with Docker Desktop on Mac)

The image contains only Python, dependencies, helpers and the YAML profile.
The XAPK, extracted resources and private results use **bind mounts**, never image
layers. From the repository directory:

```sh
docker build -t conga8290-key .
mkdir -p artifacts private
chmod 700 artifacts private

# Offline preparation: replace /path/to/... with the compatible local XAPK.
docker run --rm --network none --log-driver none --read-only \
  --user "$(id -u):$(id -g)" --tmpfs /tmp \
  --mount "type=bind,src=$(pwd)/artifacts,dst=/app/artifacts" \
  --mount "type=bind,src=/path/to/Cecotec_1.2.9_APKPure.xapk,dst=/input/app.xapk,readonly" \
  conga8290-key --xapk /input/app.xapk --check

# Interactive recovery: a new login, without robot commands.
docker run --rm -it --log-driver none --read-only \
  --user "$(id -u):$(id -g)" --tmpfs /tmp \
  --mount "type=bind,src=$(pwd)/artifacts,dst=/app/artifacts,readonly" \
  --mount "type=bind,src=$(pwd)/private,dst=/app/private" \
  conga8290-key
```

`-it` is required when using prompts. Add `-c 34 -u EMAIL` after the image name to
skip those prompts; `-p` is supported but discouraged. `--user` before the image
name is the Docker UID/GID, not the Cecotec email. Do not use `--privileged`, host
networking or published ports. Do not run these instructions with `sudo`: files
must belong to your user. Recovery needs outbound HTTPS; preparation and tests
run without cloud access.

To test the image without an account or APK:

```sh
docker build --target tests -t conga8290-tests .
```

## Configure Tuya Local

1. Install `make-all/tuya-local` in HA (for example through HACS).
2. Copy `cecotec_conga8290_vacuum.yaml` to:
   `/config/custom_components/tuya_local/devices/cecotec_conga8290_vacuum.yaml`.
3. Reload/restart HA as required by the Tuya Local installation workflow.
4. Configure the robot with its LAN IP, recovered `id` and `local_key`, using
   protocol **3.3**. The script does not discover the IP or modify HA automatically.

Keep a backup of the profile: a HACS update may overwrite it.
Avoid running another LAN client while HA owns the robot's connection.

### Extended experimental controls

The YAML now defines **56 entities** (25 enabled, 31 disabled by default), covering
all scalar fields in the cached product schema. It adds cleaning patterns,
vacuum/mop work mode, mopping intensity, Y-mopping, carpet settings, sound/volume,
DND, consumables and lifetime totals. Uncertain controls, hardware-specific
features, movement and resets are disabled by default. Raw room/map/schedule
payloads are not guessed. See [PROFILE.md](PROFILE.md) for the complete inventory,
safety caveats and the assessment of `tuya-vacuum-maps`.

The original six entity mappings are preserved. The extended profile was loaded
on the test HA instance: 56 registered entities, 25 enabled with valid read states
and 31 disabled by default. No robot commands were sent during deployment. The
recovery script does not deploy the profile or modify HA automatically.

### Maps (experimental, read-only)

A Cecotec OEM historical map was downloaded and decoded as v2 with seven rooms,
without a Tuya IoT project or robot upload request. The fixed live objects are
currently absent. Camera-only experimental source reuses the cornguo fork's camera
and Tuya Local device association with an imported historical snapshot; it has
**not been installed or runtime-validated in HA**. See [MAPS.md](MAPS.md).
No private map or account/storage credential is included. Room cleaning and live
refresh are not implemented, and the recovery script is unchanged.

## Status and limitations

### Shared versus device-specific data

| Data | Scope |
| --- | --- |
| YAML, DP IDs/types and `productId` (`kofl9ubyyyfznpxw`) | Profile for the same compatible product, not a particular unit. |
| OEM registration, certificate and APK material | Shared by that compatible app version; not account credentials or the robot's key. |
| LAN protocol 3.3 | Verified on the test robot; not guaranteed for other variants/firmware. |
| `id` / `devId` | Each robot's identifier; do not confuse it with the `id` under YAML `products`. |
| `local_key` | Key for each robot/provisioning; not shared between units and may change after re-pairing/reset. |
| LAN IP | Depends on your network/DHCP, not a fixed property of the model. |
| Account, country/region and homes | Specific to each user/account. |
| Tokens/sessions and the Python client's deviceId | Specific to each run/login; this deviceId is not the robot's ID. |

The robot's key **is retrieved from the cloud after account authentication**:
it is not calculated from the ID, and there is no universal key for all Conga 8290
robots. The YAML is reusable for units with the same product/schema; it has not
been tested with every unit sold under the 8290 name or every firmware version.

Original packaging verified offline: **67 tests** on macOS (Python 3.12), Linux amd64
(Python 3.13) and Linux Docker amd64 (Python 3.13). Bootstrap with actual compatible
resources was verified on Mac and Docker, without network access or authentication.
The Docker image was tested as a non-root user with a read-only root filesystem
and bind-mounted resources. Docker Desktop on Mac was not run during validation.
The expanded profile adds seven regression tests (**74 package tests** total,
verified on macOS after the deployment fix);
offline schema checks also verify enum values, types, ranges and scalar coverage.

OEM-UI login and cloud recovery were verified with the test account/model/APK;
the key matches the original capture. The YAML was loaded in HA and LAN 3.3 reads
were verified. The packaged selector and prompts are tested offline with synthetic
data: tests never perform another real login. Physical controls, maps, rooms,
other accounts/regions/APKs and prolonged operation without Internet access have
not been validated. This is a one-off tool, not a daemon or permanent cloud
integration. Python does not guarantee secure erasure of secrets from RAM.

## Tests

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Tests require no APK, account, robot or Home Assistant. Personal captures, Android
research and dumps are not included. `.gitignore` excludes credential files and
local resources; always review files before publishing anyway.
