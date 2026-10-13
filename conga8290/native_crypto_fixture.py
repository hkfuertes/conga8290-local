"""Run the supplied SDK's ARM64 crypto offline with synthetic JNI inputs.

Research oracle, NOT an Android runtime, login client, or credential extractor.
Maps one exact shipped ELF in Unicorn, resolves its relocations, and provides
minimal libc/JNI/string shims. No device, network, account data or protection
changes. Unknown imports fail closed; target instructions have time/count bounds.
"""
import argparse
import hashlib
import hmac
import io
import json
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (
    UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
    UC_ARM64_REG_X4, UC_ARM64_REG_X5, UC_ARM64_REG_X6, UC_ARM64_REG_X7,
    UC_ARM64_REG_X8, UC_ARM64_REG_LR, UC_ARM64_REG_PC, UC_ARM64_REG_SP,
    UC_ARM64_REG_TPIDR_EL0,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / 'artifacts/cloud-native/libthing_security.so'
EXPECTED_SHA256 = '7340fe7f3c0f999c5913b8a8d3effb603be3631bd1cea6455806178ffd18b38f'
REGS = [UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
        UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5,
        UC_ARM64_REG_X6, UC_ARM64_REG_X7, UC_ARM64_REG_X8]


class NativeFixture:
    ARTIFACT = ARTIFACT
    EXPECTED_SHA256 = EXPECTED_SHA256
    MAX_INSTRUCTIONS = 500_000
    TIMEOUT_MICROS = 5_000_000
    BASE = 0x1000000
    STUBS = 0x2000000
    HEAP = 0x3000000
    STACK = 0x4000000
    TLS = 0x5000000

    def __init__(self):
        data = self.ARTIFACT.read_bytes()
        if hashlib.sha256(data).hexdigest() != self.EXPECTED_SHA256:
            raise ValueError('unexpected_native_artifact')
        elf = ELFFile(io.BytesIO(data))
        if elf['e_machine'] != 'EM_AARCH64' or elf.elfclass != 64:
            raise ValueError('expected_arm64_elf')
        self.uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        loads = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        end = max(s['p_vaddr'] + s['p_memsz'] for s in loads)
        self.uc.mem_map(self.BASE, (end + 0xfff) & ~0xfff)
        for segment in loads:
            self.uc.mem_write(self.BASE + segment['p_vaddr'], segment.data())
        self.uc.mem_map(self.STUBS, 0x10000)
        self.uc.mem_map(self.HEAP, 0x400000)
        self.uc.mem_map(self.STACK, 0x100000)
        self.uc.mem_map(self.TLS, 0x1000)
        self.cursor = self.HEAP
        self.allocation_sizes = {}
        self.hooks = {}
        self.imports_called = set()
        self.stubs_by_name = {}
        self.stop = self.STUBS + 0xfff0
        self.failure = None
        self.completed = False
        self.uc.reg_write(UC_ARM64_REG_TPIDR_EL0, self.TLS)
        for section in elf.iter_sections():
            if section['sh_type'] != 'SHT_RELA':
                continue
            symbols = elf.get_section(section['sh_link'])
            for relocation in section.iter_relocations():
                kind = relocation['r_info_type']
                if kind == 1027:  # R_AARCH64_RELATIVE
                    value = self.BASE + relocation['r_addend']
                elif kind in [257, 1025, 1026]:  # ABS64 / GLOB_DAT / JUMP_SLOT
                    symbol = symbols.get_symbol(relocation['r_info_sym'])
                    if symbol['st_shndx'] != 'SHN_UNDEF':
                        value = self.BASE + symbol['st_value'] + relocation['r_addend']
                    else:
                        value = self.import_stub(symbol.name)
                else:
                    raise ValueError('unsupported_relocation_type')
                self.write_u64(self.BASE + relocation['r_offset'], value)
        # Only stub dispatch/return needs Python. A global instruction callback
        # makes the multiprecision carrier parser exceed its CPU budget on Linux.
        # Unicorn still enforces emu_start's instruction/time bounds everywhere.
        self.uc.hook_add(UC_HOOK_CODE, self.on_code,
                         begin=self.STUBS, end=self.STUBS + 0xffff)

    def allocate(self, size):
        if not 0 <= size <= 0x100000:
            raise ValueError('allocation_out_of_bounds')
        address = self.cursor
        self.cursor += (size + 31) & ~15
        if self.cursor > self.HEAP + 0x400000:
            raise ValueError('fixture_heap_exhausted')
        self.allocation_sizes[address] = size
        return address

    def bytes_at(self, address, size):
        if not 0 <= size <= 0x100000:
            raise ValueError('read_size_out_of_bounds')
        return bytes(self.uc.mem_read(address, size))

    def cstring(self, address):
        if not address:
            raise ValueError('null_cstring')
        result = bytearray()
        for offset in range(0x10000):
            byte = self.bytes_at(address + offset, 1)[0]
            if byte == 0:
                return bytes(result)
            result.append(byte)
        raise ValueError('unterminated_cstring')

    def put(self, data):
        address = self.allocate(len(data) + 1)
        self.uc.mem_write(address, data + b'\0')
        return address

    def read_u64(self, address):
        return struct.unpack('<Q', self.bytes_at(address, 8))[0]

    def write_u64(self, address, value):
        self.uc.mem_write(address, struct.pack('<Q', value))

    def string_value(self, address):
        tag = self.bytes_at(address, 1)[0]
        if tag & 1:
            size = self.read_u64(address + 8)
            return self.bytes_at(self.read_u64(address + 16), size)
        return self.bytes_at(address + 1, tag >> 1)

    def set_string(self, address, data):
        if len(data) <= 22:
            self.uc.mem_write(address, bytes([len(data) << 1]) + data + bytes(23 - len(data)))
        else:
            pointer = self.put(data)
            self.uc.mem_write(address, struct.pack('<QQQ', ((len(data) + 16) & ~15) | 1,
                                                   len(data), pointer))

    def stub(self, name, callback):
        address = self.STUBS + len(self.hooks) * 16
        if address >= self.stop:
            raise ValueError('stub_table_exhausted')
        self.hooks[address] = (name, callback)
        return address

    def import_stub(self, name):
        if name not in self.stubs_by_name:
            self.stubs_by_name[name] = self.stub(name, lambda args: self.import_call(name, args))
        return self.stubs_by_name[name]

    def import_call(self, name, args):
        a, b, c = args[:3]
        self.imports_called.add(name)
        if name in ['malloc', '_Znwm']:
            return self.allocate(a)
        if name == 'calloc':
            return self.allocate(a * b)
        if name in ['free', '_ZdlPv']:
            return 0
        if name in ['strlen', '__strlen_chk']:
            return len(self.cstring(a))
        if name in ['memcpy', 'memmove', '__memcpy_chk', '__memmove_chk']:
            self.uc.mem_write(a, self.bytes_at(b, c))
            return a
        if name in ['memset', '__memset_chk']:
            if c > 0x100000:
                raise ValueError('write_size_out_of_bounds')
            self.uc.mem_write(a, bytes([b & 255]) * c)
            return a
        if name == '__vsprintf_chk':
            # Only the verified digest-byte "%02x" formatting operation.
            if self.cstring(args[3]) != b'%02x':
                raise ValueError('unsupported_fixture_format')
            va_list = args[4]
            gr_top = self.read_u64(va_list + 8)
            gr_offset = struct.unpack('<i', self.bytes_at(va_list + 24, 4))[0]
            if gr_offset >= 0:
                raise ValueError('unsupported_fixture_varargs_stack')
            value = struct.unpack('<I', self.bytes_at(gr_top + gr_offset, 4))[0]
            if value > 255:
                raise ValueError('expected_single_digest_byte')
            text = f'{value:02x}'.encode('ascii')
            self.uc.mem_write(a, text + b'\0')
            return len(text)
        # std::__ndk1::basic_string append overloads, only synthetic strings.
        if name.startswith('_ZNSt6__ndk112basic_string') and '6append' in name:
            suffix = self.cstring(b) if name.endswith('EPKc') else self.bytes_at(b, c)
            self.set_string(a, self.string_value(a) + suffix)
            return a
        raise ValueError('unsupported_called_import:' + name)

    def on_code(self, uc, address, _size, _user):
        if address == self.stop:
            self.completed = True
            uc.emu_stop()
        elif address in self.hooks:
            name, callback = self.hooks[address]
            try:
                result = callback([uc.reg_read(r) for r in REGS])
                uc.reg_write(UC_ARM64_REG_X0, result & ((1 << 64) - 1))
                uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
            except Exception as exc:
                self.failure = exc
                uc.emu_stop()

    def call(self, address, *args):
        self.failure = None
        self.completed = False
        self.uc.reg_write(UC_ARM64_REG_SP, self.STACK + 0xf0000)
        self.uc.reg_write(UC_ARM64_REG_LR, self.stop)
        for index, register in enumerate(REGS):
            self.uc.reg_write(register, args[index] if index < len(args) else 0)
        # Bounded native CPU emulation, never subprocess-execute the Android ELF.
        self.uc.emu_start(self.BASE + address, self.stop + 4,
                          timeout=self.TIMEOUT_MICROS, count=self.MAX_INSTRUCTIONS)
        if self.failure:
            raise self.failure
        if not self.completed:
            raise RuntimeError('native_fixture_did_not_return_within_budget')
        return self.uc.reg_read(UC_ARM64_REG_X0)

    def native_hmac(self, key, message):
        result = self.allocate(32)
        status = self.call(0x18458, self.BASE + 0x34bd0, self.put(key), len(key),
                           self.put(message), len(message), result)
        if status != 0:
            raise RuntimeError('native_hmac_failed')
        return self.bytes_at(result, 32)

    def native_request_key(self, request_id, synthetic_secret, ecode=None):
        # Supply synthetic already-initialised native key material, never read it
        # from a phone/account. This doesn't validate app-secret initialisation.
        self.set_string(self.BASE + 0x3ab60, synthetic_secret)
        table = self.allocate(0x700)
        env = self.allocate(8)
        self.write_u64(env, table)
        self.write_u64(table + 0x548, self.stub('GetStringUTFChars', lambda a: a[1]))
        self.write_u64(table + 0x580, self.stub('NewByteArray', lambda a: self.allocate(a[1])))

        def set_region(args):
            _, array, start, size, data = args[:5]
            self.uc.mem_write(array + start, self.bytes_at(data, size))
            return 0

        self.write_u64(table + 0x680, self.stub('SetByteArrayRegion', set_region))
        result = self.call(0x15dc8, env, 0, self.put(request_id),
                           self.put(ecode) if ecode is not None else 0)
        if not result:
            raise RuntimeError('native_request_key_failed')
        return self.bytes_at(result, 16)


def run_fixtures():
    fixture = NativeFixture()
    # RFC 4231 test case 1. The native HMAC itself is NOT shimmed.
    expected = bytes.fromhex('b0344c61d8db38535ca8afceaf0bf12b'
                             '881dc200c9833da726e9376c2e32cff7')
    if fixture.native_hmac(bytes([0x0b]) * 20, b'Hi There') != expected:
        raise AssertionError('native_rfc4231_mismatch')
    request = b'00000000-0000-4000-8000-000000000000'
    secret = b'synthetic-native-secret'
    for ecode in [None, b'', b'synthetic-session-ecode']:
        message = secret if ecode is None else secret + b'_' + ecode
        python_key = hmac.new(request, message, hashlib.sha256).hexdigest()[:16].encode('ascii')
        native_key = fixture.native_request_key(request, secret, ecode)
        if native_key != python_key:
            raise AssertionError('native_request_key_mismatch')
    return {'artifact_sha256': EXPECTED_SHA256,
            'execution': 'bounded_offline_unicorn_arm64',
            'rfc4231_native_hmac_matches': True,
            'synthetic_request_key_cases_match_python': 3,
            'app_key_initialisation_verified': False,
            'cloud_login_verified': False, 'network_or_phone_access': False,
            'shimmed_imports_called': sorted(fixture.imports_called)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, help='Optional NEW redacted evidence file')
    args = parser.parse_args()
    result = run_fixtures()
    if args.evidence:
        with args.evidence.open('x') as handle:
            json.dump(result, handle, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
