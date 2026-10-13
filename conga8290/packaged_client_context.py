"""Pinned APK manifest -> minimal client context, without Android/account access.

Only package/version/UMENG_CHANNEL are selected from binary XML. Credentials and
context are returned in memory, never printed or persisted. Client deviceId is a
new random installation identifier, NOT copied from the phone or robot.
"""
import hashlib
import re
import secrets
import struct
import zipfile

from .packaged_oem_identity import APK, APK_SHA256, packaged_registration

NONE = 0xffffffff


def manifest_context(data):
    if not isinstance(data, bytes) or not 8 <= len(data) <= 1048576:
        raise ValueError('bounded_binary_manifest_required')
    kind, header, total = struct.unpack_from('<HHI', data)
    if kind != 3 or header != 8 or total != len(data):
        raise ValueError('unexpected_binary_xml_header')
    strings, result, channel_values = None, {}, []
    offset = header

    def index(value):
        if strings is None or not 0 <= value < len(strings):
            raise ValueError('invalid_manifest_string_index')
        return strings[value]

    while offset < total:
        if total - offset < 8:
            raise ValueError('truncated_manifest_chunk')
        kind, size_header, size = struct.unpack_from('<HHI', data, offset)
        if not 8 <= size_header <= size <= total - offset:
            raise ValueError('invalid_manifest_chunk_bounds')
        chunk = data[offset:offset + size]
        if kind == 1:
            if strings is not None or size_header < 28:
                raise ValueError('unexpected_manifest_string_pool')
            count, styles, flags, start, styles_start = struct.unpack_from('<IIIII', chunk, 8)
            if count > 65536 or start < size_header + 4 * (count + styles) or start > size:
                raise ValueError('invalid_manifest_string_pool_bounds')
            strings = []
            for i in range(count):
                position = start + struct.unpack_from('<I', chunk, size_header + 4 * i)[0]
                def length(unit):
                    nonlocal position
                    if position + unit > len(chunk):
                        raise ValueError('truncated_manifest_string_length')
                    value = int.from_bytes(chunk[position:position + unit], 'little')
                    position += unit
                    high = 1 << (8 * unit - 1)
                    if value & high:
                        if position + unit > len(chunk):
                            raise ValueError('truncated_manifest_string_length')
                        value = ((value & (high - 1)) << (8 * unit)) | int.from_bytes(chunk[position:position + unit], 'little')
                        position += unit
                    return value
                if flags & 0x100:
                    length(1)
                    length_bytes = length(1)
                    encoding, terminator = 'utf8', 1
                else:
                    length_bytes = length(2) * 2
                    encoding, terminator = 'utf-16le', 2
                end = position + length_bytes
                if end + terminator > len(chunk) or chunk[end:end + terminator] != bytes(terminator):
                    raise ValueError('truncated_manifest_string')
                strings.append(chunk[position:end].decode(encoding))
        elif kind == 0x102:
            if size_header != 16 or size < 36:
                raise ValueError('unsupported_manifest_element_layout')
            namespace, name, attr_start, attr_size, attr_count = struct.unpack_from('<IIHHH', chunk, 16)
            begin = 16 + attr_start
            if attr_size < 20 or begin < 36 or begin + attr_count * attr_size > size:
                raise ValueError('invalid_manifest_attribute_bounds')
            tag = index(name)
            selected = {}
            meta_value = None
            for i in range(attr_count):
                position = begin + i * attr_size
                ns, name_index, raw = struct.unpack_from('<III', chunk, position)
                attr_name = index(name_index)
                if (tag == 'manifest' and attr_name in ['package', 'versionName'] or
                        tag == 'meta-data' and attr_name in ['name', 'value']):
                    value_size, reserved, value_kind, value = struct.unpack_from('<HBBI', chunk, position + 12)
                    if tag == 'meta-data' and attr_name == 'value':
                        meta_value = value_size, reserved, value_kind, value
                        continue
                    if value_size != 8 or reserved or value_kind != 3:
                        raise ValueError('selected_manifest_attribute_not_literal_string')
                    selected[attr_name] = index(value)
            if tag == 'manifest':
                if result:
                    raise ValueError('duplicate_manifest_root')
                result.update(selected)
            if tag == 'meta-data' and selected.get('name') == 'UMENG_CHANNEL':
                if not meta_value or meta_value[:3] != (8, 0, 3):
                    raise ValueError('selected_manifest_attribute_not_literal_string')
                channel_values.append(index(meta_value[3]))
        offset += size
    if (result.get('package') != 'es.cecotec.forceclima' or
            not re.fullmatch(r'\d+\.\d+\.\d+', result.get('versionName', '')) or
            len(channel_values) != 1 or not isinstance(channel_values[0], str) or not channel_values[0]):
        raise ValueError('expected_oem_manifest_context_missing')
    return {'package': result['package'], 'version': result['versionName'], 'channel': channel_values[0]}


def packaged_client_context():
    if hashlib.sha256(APK.read_bytes()).hexdigest() != APK_SHA256:
        raise ValueError('unexpected_apk')
    with zipfile.ZipFile(APK) as archive:
        manifest = manifest_context(archive.read('AndroidManifest.xml'))
    app_id, _secret = packaged_registration()
    # SmartApplication sets mSdk=true. AppInitializer:864-868 sets this ttid.
    # It is a packaged channel label, NOT the app version or a guessed login token.
    return {'mAppId': app_id, 'mAppVersion': manifest['version'],
            'mTtid': 'sdk_' + manifest['channel'] + '@' + app_id,
            # ThingSdk.init's OEM overload (1829-1830) supplies CHANNEL_OEM;
            # mSdk=true affects ttid construction, not this network channel.
            'mDeviceId': secrets.token_hex(22), 'mChannel': 'oem'}
