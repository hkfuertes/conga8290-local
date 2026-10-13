"""Bounded offline oracle for the shipped SDK key-carrier parser.

No phone, network, account data, login or protection modification. Returned
registration strings are sensitive: callers must not print or persist them.
"""
import struct

from .native_crypto_fixture import NativeFixture, ROOT
from .key_carrier import carrier_hash, carrier_metadata


class KeyCarrierFixture(NativeFixture):
    ARTIFACT = ROOT / 'artifacts/cloud-native/libthing_security_algorithm.so'
    EXPECTED_SHA256 = '401954bae1c402b3b4b4145ebd5b180bd90d0e18f02ff67b6c804e143512f903'
    # Carrier reconstruction includes the shipped multiprecision arithmetic;
    # its per-call budget is larger than a simple HMAC, but remains bounded.
    MAX_INSTRUCTIONS = 10_000_000
    TIMEOUT_MICROS = 15_000_000

    def import_call(self, name, args):
        if name == 'abs':
            self.imports_called.add(name)
            value = args[0] & 0xffffffff
            signed = value if value < 0x80000000 else value - 0x100000000
            return abs(signed) & 0xffffffff
        if name == 'labs':
            self.imports_called.add(name)
            value = args[0] & 0xffffffffffffffff
            signed = value if value < 0x8000000000000000 else value - 0x10000000000000000
            return abs(signed) & 0xffffffffffffffff
        if name in ['strchr', '__strchr_chk']:
            self.imports_called.add(name)
            text = self.cstring(args[0]) + b'\0'
            if name == '__strchr_chk' and len(text) > args[2]:
                raise ValueError('fixture_string_buffer_overflow')
            index = text.find(bytes([args[1] & 255]))
            return args[0] + index if index >= 0 else 0
        if name == 'realloc':
            self.imports_called.add(name)
            address, size = args[:2]
            if address and address not in self.allocation_sizes:
                raise ValueError('unknown_fixture_realloc_pointer')
            if not size:
                return 0
            result = self.allocate(size)
            if address:
                self.uc.mem_write(result, self.bytes_at(address, min(size, self.allocation_sizes[address])))
            return result
        if name == '__vsnprintf_chk':
            self.imports_called.add(name)
            target, capacity, _flags, object_size, format_address, va_list = args[:6]
            format_string = self.cstring(format_address)
            if format_string not in [b'%02x', b'%02X'] or capacity > 0x100000:
                raise ValueError('unsupported_fixture_format')
            gr_top = self.read_u64(va_list + 8)
            gr_offset = struct.unpack('<i', self.bytes_at(va_list + 24, 4))[0]
            if gr_offset >= 0:
                raise ValueError('unsupported_fixture_varargs_stack')
            value = struct.unpack('<I', self.bytes_at(gr_top + gr_offset, 4))[0]
            if value > 255:
                raise ValueError('expected_single_carrier_byte')
            text = format(value, '02X' if format_string == b'%02X' else '02x').encode('ascii')
            written = text[:max(0, capacity - 1)] + b'\0' if capacity else b''
            if object_size != 0xffffffffffffffff and len(written) > object_size:
                raise ValueError('fixture_format_buffer_overflow')
            if written:
                self.uc.mem_write(target, written)
            return len(text)
        return super().import_call(name, args)

    def native_hash(self, value):
        carrier_hash(value)  # Validate NUL/size before calling the real ELF.
        return self.call(0x52d0, self.put(value)) & 0xffffffff

    def header_status(self, data):
        if len(data) < 54:
            raise ValueError('truncated_key_carrier_header')
        address = self.put(data)
        return self.call(0x4b0c, address, address + 14)

    def read_keys(self, selector, content):
        carrier_hash(selector)
        carrier_metadata(content)
        pointer, count = self.allocate(8), self.allocate(4)
        status = self.call(0x4a4c, self.put(selector), pointer, count, self.put(content))
        if status != 0:
            return status, []
        size = struct.unpack('<I', self.bytes_at(count, 4))[0]
        if not 1 <= size <= 5:
            raise ValueError('native_carrier_key_count_out_of_bounds')
        table = self.read_u64(pointer)
        values = [self.cstring(self.read_u64(table + 8 * i)) for i in range(size)]
        return status, values
