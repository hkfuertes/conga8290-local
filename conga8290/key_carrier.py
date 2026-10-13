"""Offline validation/hash primitives for the SDK's packaged BMP carrier.

No credential extraction, network or optional native-emulation dependencies.
"""
import struct


def carrier_hash(value):
    if not isinstance(value, bytes) or b'\0' in value or len(value) > 4096:
        raise ValueError('invalid_carrier_selector')
    result = 0
    for byte in value:
        result = (31 * result + byte) & 0xffffffff
    signed = result if result < 0x80000000 else result - 0x100000000
    return abs(signed) & 0xffffffff


def carrier_metadata(data):
    if not isinstance(data, bytes) or len(data) < 54 or data[:2] != b'BM':
        raise ValueError('invalid_key_carrier_header')
    declared = struct.unpack_from('<I', data, 2)[0]
    offset = struct.unpack_from('<I', data, 10)[0]
    bits = struct.unpack_from('<H', data, 28)[0]
    compression = struct.unpack_from('<I', data, 30)[0]
    if (not 10240 <= declared <= 0x200000 or declared > len(data) or
            not 54 <= offset <= declared - 54 or bits not in [24, 32] or compression):
        raise ValueError('unsupported_key_carrier_layout')
    # Native read_keys always passes content+54, even though its size calculation
    # uses the BMP offset. Reject other offsets rather than model unsafe reads.
    if offset != 54:
        raise ValueError('unsupported_key_carrier_pixel_offset')
    return {'declared_size': declared, 'pixel_offset': offset,
            'pixel_length': declared - offset, 'bits_per_pixel': bits}
