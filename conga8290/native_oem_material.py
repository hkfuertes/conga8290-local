"""Synthetic/isolated native material-construction oracle, NOT full OEM init.

Runs genuine constructors and the command-0 string-joining segment. Does not
execute/bypass its preceding signature checks, or claim whole-command success.
All inputs/results stay in memory. No Android/account/network access.
"""
from .native_crypto_fixture import NativeFixture
from unicorn.arm64_const import UC_ARM64_REG_X23, UC_ARM64_REG_X27, UC_ARM64_REG_X28, UC_ARM64_REG_X29, UC_ARM64_REG_SP, UC_ARM64_REG_PC


class MaterialFixture(NativeFixture):
    def import_call(self, name, args):
        a, b, c = args[:3]
        if name == '__cxa_atexit':
            self.imports_called.add(name)
            return 0  # Registering a destructor has no effect before teardown.
        if name == 'getauxval' and a in [16, 26]:
            self.imports_called.add(name)
            return 0  # Emulated CPU advertises no optional acceleration features.
        if name == '__system_property_get' and self.cstring(a) == b'ro.arch':
            self.imports_called.add(name)
            self.uc.mem_write(b, b'\0')
            return 0  # No Android system-property service in this PC fixture.
        if name == '_Znam':
            self.imports_called.add(name)
            return self.allocate(a)
        if name == '_ZdaPv':
            self.imports_called.add(name)
            return 0
        if name.startswith('_ZNSt6__ndk112basic_string'):
            self.imports_called.add(name)
            if '6resizeEmc' in name:
                if b > 0x100000:
                    raise ValueError('fixture_string_size_out_of_bounds')
                old = self.string_value(a)
                self.set_string(a, old[:b] + bytes([c & 255]) * max(0, b - len(old)))
                return a
            if '7reserveEm' in name:
                if b > 0x100000:
                    raise ValueError('fixture_string_size_out_of_bounds')
                return a  # Capacity is not observable by the hash caller.
            if '9push_backEc' in name:
                self.set_string(a, self.string_value(a) + bytes([b & 255]))
                return a
            if '6appendEmc' in name:
                if b > 0x100000:
                    raise ValueError('fixture_string_size_out_of_bounds')
                self.set_string(a, self.string_value(a) + bytes([c & 255]) * b)
                return a
            if '6assignEPKc' in name:
                self.set_string(a, self.cstring(b))
                return a
            if 'aSERKS5_' in name:
                self.set_string(a, self.string_value(b))
                return a
        if name == 'strcat':
            self.imports_called.add(name)
            output = self.cstring(a) + self.cstring(b) + b'\0'
            if len(output) > 0x10000:
                raise ValueError('fixture_string_size_out_of_bounds')
            self.uc.mem_write(a, output)
            return a
        return super().import_call(name, args)

    def constructors(self):
        for address in [0x2b9fc, 0x2c030, 0x18114]:
            self.call(address)

    def hex_bytes(self, data):
        if len(data) > 4096:
            raise ValueError('fixture_hex_input_out_of_bounds')
        output = self.allocate(len(data) * 2 + 1)
        self.call(0x17ba4, self.put(data), len(data), output)
        return self.cstring(output)

    def digest_hex(self, data):
        source, output = self.allocate(24), self.allocate(24)
        self.set_string(source, data)
        self.call(0x13d78, source, output)
        return self.string_value(output)

    def native_ch_key(self, app_id, package, fingerprint):
        self.set_string(self.BASE + 0x3ab90, package)
        self.set_string(self.BASE + 0x3ab48, fingerprint)
        table, env = self.allocate(0x700), self.allocate(8)
        self.write_u64(env, table)
        value = self.put(app_id)
        self.write_u64(table + 0x558, self.stub('GetArrayLength', lambda a: len(app_id)))
        self.write_u64(table + 0x5c0, self.stub('GetByteArrayElements', lambda a: value))
        self.write_u64(table + 0x538, self.stub('NewStringUTF', lambda a: a[1]))
        result = self.call(0x16a60, env, 0, 0, value)
        return self.cstring(result)

    def join_segment(self, package, fingerprint, decoded_key, app_secret):
        if any(not isinstance(v, bytes) or len(v) > 4096 for v in
               [package, fingerprint, decoded_key, app_secret]):
            raise ValueError('fixture_material_input_out_of_bounds')
        self.set_string(self.BASE + 0x3ab90, package)
        self.set_string(self.BASE + 0x3ab48, fingerprint)
        entry = self.allocate(24)
        self.set_string(entry, decoded_key)
        vector = self.BASE + 0x3ab30
        self.write_u64(vector, entry)
        self.write_u64(vector + 8, entry + 24)
        self.write_u64(vector + 16, entry + 24)
        frame = self.STACK + 0xf0000
        self.uc.reg_write(UC_ARM64_REG_X29, frame)
        self.uc.reg_write(UC_ARM64_REG_SP, frame - 0x1a0)
        self.uc.reg_write(UC_ARM64_REG_X23, vector)
        self.uc.reg_write(UC_ARM64_REG_X27, self.BASE + 0x3ab48)
        self.uc.reg_write(UC_ARM64_REG_X28, self.put(b'synthetic-unused-app-id'))
        self.set_string(frame - 0xb0, app_secret)
        # Exact assembly fragment, stopping before whole-command JNI cleanup.
        start, stop = self.BASE + 0x155e8, self.BASE + 0x157f4
        self.failure = None
        self.uc.emu_start(start, stop, timeout=self.TIMEOUT_MICROS, count=self.MAX_INSTRUCTIONS)
        if self.failure:
            raise self.failure
        if self.uc.reg_read(UC_ARM64_REG_PC) != stop:
            raise RuntimeError('native_join_segment_budget_exhausted')
        return self.string_value(self.BASE + 0x3ab60)
