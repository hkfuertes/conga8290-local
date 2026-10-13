"""Offline experimental camera boundary tests; no HA, account or real floor plan."""
import ast
import dataclasses
import importlib.util
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
from types import ModuleType
import unittest
import yaml


COMPONENT = Path(__file__).resolve().parents[1] / 'experimental/read_only_maps/custom_components/tuya_vacuum_maps'
PACKAGE = '_conga_map_offline_tests'
package = ModuleType(PACKAGE)
package.__path__ = [str(COMPONENT)]
sys.modules[PACKAGE] = package


def load(name):
    spec = importlib.util.spec_from_file_location(f'{PACKAGE}.{name}', COMPONENT / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


decoder = load('map_cache_decoder')
adapter = load('hacs_v2_map_adapter')
renderer = load('map_render')


def synthetic_layout():
    record = bytearray(47)
    record[:8] = struct.pack('>4H', 1, 1, 1, 1)
    record[26] = 5
    record[27:32] = b'Room1'
    body = bytes([0, 1, 15, 10]) + b'\x00\x01' + record
    header = bytearray(24)
    header[0] = 2
    header[4:8] = struct.pack('>2H', 2, 2)
    header[18:22] = struct.pack('>I', len(body))
    return bytes(header) + body


def snapshot_reader():
    source = ast.parse((COMPONENT / 'coordinator.py').read_text())
    node = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == 'read_snapshot')
    scope = {'os': os, 'stat': stat, 'MAX_INPUT': decoder.MAX_INPUT,
             'MapData': renderer.MapData, 'render_v2_map': adapter.render_v2_map}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'snapshot-reader', 'exec'), scope)
    return scope['read_snapshot']


class ReadOnlyMapsTests(unittest.TestCase):
    def test_public_component_is_camera_only_without_network_dependencies(self):
        self.assertIn('PLATFORMS = [Platform.CAMERA]', (COMPONENT / '__init__.py').read_text())
        manifest = json.loads((COMPONENT / 'manifest.json').read_text())
        self.assertEqual(manifest['requirements'], [])
        self.assertEqual(manifest['dependencies'], ['tuya_local'])
        forbidden = {'cloud', 'tuya_vacuum', 'room_command', 'area_cleaning', 'map_type_filter',
                     'path_style', 'room_parser', 'local_device', 'card_resource', 'requests', 'urllib'}
        for path in COMPONENT.glob('*.py'):
            tree = ast.parse(path.read_text())
            compile(tree, str(path), 'exec')
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or '').split('.')[0], forbidden)
                    if node.level:
                        self.assertTrue((COMPONENT / f'{node.module}.py').is_file())
                elif isinstance(node, ast.Import):
                    for item in node.names:
                        self.assertNotIn(item.name.split('.')[0], forbidden)

    def test_source_is_explicitly_historical_without_polling_or_writes(self):
        source = (COMPONENT / 'coordinator.py').read_text()
        self.assertIn('source_kind = "imported_history_snapshot"', source)
        self.assertIn('update_interval=None', source)
        for forbidden in ['async_set_properties', 'async_clean', 'map_upload', '.post(', 'urlopen']:
            self.assertNotIn(forbidden, source)
        flow = (COMPONENT / 'config_flow.py').read_text()
        self.assertIn('data={"device_id": device_id}', flow)
        self.assertIn('if self._async_current_entries():', flow)
        for forbidden in ['client_secret', 'password', 'email_token', 'login(']:
            self.assertNotIn(forbidden, flow)

    def test_real_public_mapdata_dataclass_accepts_v2_adapter(self):
        result = adapter.render_v2_map(synthetic_layout(), renderer.MapData)
        self.assertTrue(dataclasses.is_dataclass(result))
        self.assertIsInstance(result, renderer.MapData)
        self.assertTrue(result.image.startswith(b'\x89PNG'))
        self.assertEqual(result.rooms, {1: 'Room1'})
        self.assertEqual(result.map_order, [])
        self.assertIsNone(result.current_room)
        self.assertIsNone(result.vacuum_position)

    def test_layout_decoder_supports_bounded_lz4(self):
        raw = synthetic_layout()
        body = raw[24:]
        compressed = bytes([0xf0, len(body) - 15]) + body
        header = bytearray(raw[:24])
        header[22:24] = struct.pack('>H', len(compressed))
        self.assertEqual(decoder.decode_layout(bytes(header) + compressed), decoder.decode_layout(raw))
        self.assertEqual(decoder.decompress_lz4_block(b'\x11a\x01\x00\x00', 6), b'aaaaaa')

    def test_bad_layout_headers_and_trailing_bytes_fail_closed(self):
        valid = synthetic_layout()
        for value in [b'', b'\x01' + valid[1:], valid[:-1], valid + b'\x00']:
            with self.subTest(size=len(value)), self.assertRaises(decoder.MapFormatError):
                decoder.decode_layout(value)

    def test_lz4_bad_offsets_and_output_budgets_fail_closed(self):
        for block, size in [(b'\x10a\x00\x00', 5), (b'\x10a\x02\x00', 5),
                            (b'\x30abc', 2), (b'\xf0', 16)]:
            with self.assertRaises(decoder.MapFormatError):
                decoder.decompress_lz4_block(block, size)

    def test_private_snapshot_reader_and_file_boundary(self):
        reader = snapshot_reader()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layout.bin'
            path.write_bytes(synthetic_layout())
            path.chmod(0o600)
            self.assertEqual(reader(path).rooms, {1: 'Room1'})
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                reader(path)
            link = path.with_name('link.bin')
            link.symlink_to(path)
            with self.assertRaises(OSError):
                reader(link)
            fifo = path.with_name('fifo.bin')
            os.mkfifo(fifo, 0o600)
            with self.assertRaises(ValueError):
                reader(fifo)

    def test_license_camera_metadata_and_device_association_preserved(self):
        self.assertIn('Copyright (c) 2024 Jaiden Labelle', (COMPONENT / 'LICENSE').read_text())
        self.assertIn('tuya_local_identifier', (COMPONENT / 'entity.py').read_text())
        camera = (COMPONENT / 'camera.py').read_text()
        self.assertIn('class VacuumMapCamera', camera)
        self.assertIn('"source_kind": self.coordinator.source_kind', camera)
        self.assertIn('"freshness_validated": False', camera)

    def test_no_real_map_artifacts_in_experimental_tree(self):
        for suffix in ['*.bin', '*.png', '*.stream', '*.so', '*.apk']:
            self.assertEqual(list(COMPONENT.rglob(suffix)), [])

    def test_dashboard_uses_standard_camera_card_without_robot_actions(self):
        path = COMPONENT.parents[1] / 'dashboard.yaml'
        config = yaml.safe_load(path.read_text())
        cards = config['views'][0]['cards']
        self.assertEqual([card['type'] for card in cards], ['markdown', 'picture-entity'])
        self.assertEqual(cards[1]['entity'], 'camera.conga_8290_map')
        self.assertEqual(cards[1]['tap_action']['action'], 'more-info')
        self.assertNotIn('call-service', path.read_text())
        self.assertNotIn('vacuum.start', path.read_text())


if __name__ == '__main__':
    unittest.main()
