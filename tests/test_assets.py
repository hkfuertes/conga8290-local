"""Synthetic local XAPK import; pinned bytes, bounds and no-overwrite semantics."""
import hashlib
import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from conga8290.assets import prepare_xapk


def synthetic_xapk(path, mismatch=False):
    payloads = {'es.cecotec.forceclima.apk': b'synthetic-base',
                'cloud-native/libthing_security.so': b'synthetic-security',
                'cloud-native/libthing_security_algorithm.so': b'synthetic-carrier'}
    split = io.BytesIO()
    with zipfile.ZipFile(split, 'w') as archive:
        for name, data in payloads.items():
            if name.startswith('cloud-native/'):
                archive.writestr('lib/arm64-v8a/' + name.split('/')[-1], data)
        archive.writestr('../../must-not-extract', b'synthetic-unrelated-file')
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('es.cecotec.forceclima.apk', b'wrong' if mismatch else payloads['es.cecotec.forceclima.apk'])
        archive.writestr('config.arm64_v8a.apk', split.getvalue())
    return {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}


class AssetTests(unittest.TestCase):
    def test_exact_local_import_is_idempotent_private_and_not_extractall(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'synthetic.xapk', root / 'artifacts'
            expected = synthetic_xapk(source)
            with patch('conga8290.assets.EXPECTED', expected):
                self.assertTrue(prepare_xapk(source, target))
                self.assertTrue(prepare_xapk(source, target))
            self.assertFalse((root / 'must-not-extract').exists())
            for name, digest in expected.items():
                path = target / name
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)

    def test_mismatch_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = synthetic_xapk(root / 'synthetic.xapk', mismatch=True)
            with patch('conga8290.assets.EXPECTED', expected), self.assertRaises(ValueError):
                prepare_xapk(root / 'synthetic.xapk', root / 'artifacts')
            self.assertFalse((root / 'artifacts').exists())

    def test_existing_incompatible_file_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = synthetic_xapk(root / 'synthetic.xapk')
            target = root / 'artifacts'
            target.mkdir(mode=0o700)
            old = target / 'es.cecotec.forceclima.apk'
            old.write_bytes(b'user-existing-file')
            old.chmod(0o600)
            with patch('conga8290.assets.EXPECTED', expected), self.assertRaises(ValueError):
                prepare_xapk(root / 'synthetic.xapk', target)
            self.assertEqual(old.read_bytes(), b'user-existing-file')
