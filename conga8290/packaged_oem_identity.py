"""Read this supplied APK's SDK registration constants in memory only.

These are application credentials, NOT the robot's local_key or a user login.
Never print the returned strings, store them in research evidence or send them
to an unverified endpoint. No Android/root/account access is required.
"""
import hashlib
from pathlib import Path
import struct
import zipfile

APK = Path(__file__).resolve().parents[1] / 'artifacts/es.cecotec.forceclima.apk'
APK_SHA256 = 'ed4356d58095a2a7cc542d34941c0040ca24ce77b90aafee3234732e9e65d3ef'
CONFIG_CLASS = 'Lcom/thingclips/sample/BuildConfig;'


def static_registration(dex):
    if dex[:4] != b'dex\n' or len(dex) < 112:
        raise ValueError('invalid_dex_header')

    def u32(offset):
        return struct.unpack_from('<I', dex, offset)[0]

    def uleb(offset):
        result = 0
        for shift in range(0, 35, 7):
            byte = dex[offset]
            offset += 1
            result |= (byte & 127) << shift
            if byte < 128:
                return result, offset
        raise ValueError('invalid_dex_uleb')

    count, offset = struct.unpack_from('<II', dex, 56)
    strings = []
    for index in range(count):
        position = u32(offset + 4 * index)
        _, position = uleb(position)
        end = dex.find(b'\0', position)
        if end < 0:
            raise ValueError('invalid_dex_string')
        strings.append(dex[position:end].decode('utf8', errors='replace'))
    count, offset = struct.unpack_from('<II', dex, 64)
    types = [strings[u32(offset + 4 * index)] for index in range(count)]
    if CONFIG_CLASS not in types:
        return None
    count, offset = struct.unpack_from('<II', dex, 80)
    fields = [strings[u32(offset + 8 * index + 4)] for index in range(count)]
    count, offset = struct.unpack_from('<II', dex, 96)
    for index in range(count):
        definition = offset + 32 * index
        if types[u32(definition)] != CONFIG_CLASS:
            continue
        position = u32(definition + 24)
        counts = []
        for _ in range(4):
            value, position = uleb(position)
            counts.append(value)
        static_fields = []
        field_index = 0
        for _ in range(counts[0]):
            delta, position = uleb(position)
            field_index += delta
            _, position = uleb(position)
            static_fields.append(fields[field_index])
        position = u32(definition + 28)
        value_count, position = uleb(position)
        if value_count > len(static_fields):
            raise ValueError('invalid_dex_static_value_count')
        values = {}
        for field in static_fields[:value_count]:
            tag = dex[position]
            position += 1
            kind, argument = tag & 31, tag >> 5
            if kind in [0x1e, 0x1f]:  # null/boolean encode no payload bytes
                value = None if kind == 0x1e else bool(argument)
            elif kind in [0x00, 0x02, 0x03, 0x04, 0x06, 0x10, 0x11, 0x17]:
                size = argument + 1
                value = int.from_bytes(dex[position:position + size], 'little')
                position += size
                if kind == 0x17:
                    value = strings[value]
            else:
                raise ValueError('unsupported_dex_static_value_type')
            if field in ['THING_SMART_APPKEY', 'THING_SMART_SECRET']:
                values[field] = value
        app_id, secret = values.get('THING_SMART_APPKEY'), values.get('THING_SMART_SECRET')
        if not isinstance(app_id, str) or not isinstance(secret, str) or not app_id or not secret:
            raise ValueError('packaged_sdk_registration_missing')
        return app_id, secret
    return None


def packaged_registration():
    if hashlib.sha256(APK.read_bytes()).hexdigest() != APK_SHA256:
        raise ValueError('unexpected_apk_artifact')
    matches = []
    with zipfile.ZipFile(APK) as archive:
        for name in archive.namelist():
            if name.startswith('classes') and name.endswith('.dex'):
                registration = static_registration(archive.read(name))
                if registration is not None:
                    matches.append(registration)
    if len(matches) != 1:
        raise ValueError('packaged_sdk_registration_not_unique')
    return matches[0]
