"""Synthetic offline IDs/areas/privacy CLI tests; no phone or real floor plan."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest

from conga8290.map_rooms import summarize_layout
import inspect_map
from test_read_only_maps import decoder, synthetic_layout


def room(identifier, name='Test'):
    return SimpleNamespace(room_id=identifier, name=name, order=1, sweep_count=1,
                           mop_count=1, vertex_count=0)


def layout(cells, rooms=None, width=3):
    return SimpleNamespace(version=2, width=width, height=len(cells)//width,
                           cells=bytes(cells), rooms=rooms if rooms is not None else [room(1)])


class MapRoomsTests(unittest.TestCase):
    def test_ids_and_cells_are_not_command_ids_or_measured_area(self):
        report = summarize_layout(layout([15, 10, 9, 23, 31, 255]))
        self.assertEqual(report['rooms'][0]['area_cells'], 2)
        self.assertEqual(report['rooms'][0]['carpet_cells'], 1)
        self.assertEqual(report['rooms'][0]['floor_cells'], 1)
        self.assertEqual(report['segmented_room_ids'], [1, 2, 3])
        self.assertEqual(report['unlisted_segment_ids'], [2, 3])
        self.assertEqual(report['unassigned_floor_cells'], 1)
        self.assertEqual(report['floor_cells'], 5)
        self.assertIsNone(report['rooms'][0]['area_m2'])
        self.assertFalse(report['command_ids_validated'])
        self.assertFalse(report['metric_scale_validated'])
        self.assertEqual(report['freshness'], 'unknown')

    def test_id_zero_empty_room_and_grid_bounds(self):
        report = summarize_layout(layout([7, 0, 15, 7, 0, 15], [room(0), room(1), room(2)]))
        self.assertEqual([r['room_id'] for r in report['rooms']], [0, 1, 2])
        self.assertEqual(report['rooms'][0]['bounds_grid_xy'], [0, 0, 0, 1])
        self.assertEqual(report['rooms'][2]['area_cells'], 0)
        self.assertIsNone(report['rooms'][2]['label_grid_xy'])

    def test_label_is_member_cell_not_empty_centroid(self):
        source = layout([15, 0, 15, 15, 0, 15, 15, 0, 15])
        x, y = summarize_layout(source)['rooms'][0]['label_grid_xy']
        self.assertEqual(source.cells[y*source.width+x], 15)

    def test_names_and_room_order_do_not_change_id(self):
        source = layout([15, 23, 0], [room(2, 'Bath'), room(1, 'Kitchen')])
        result = summarize_layout(source)['rooms']
        self.assertEqual([(r['room_id'], r['name']) for r in result], [(1, 'Kitchen'), (2, 'Bath')])
        self.assertEqual(result[0]['floor_pixel_hex'], '0f')
        self.assertEqual(result[1]['floor_pixel_hex'], '17')

    def test_decoded_metadata_and_polygon_raw_words_are_preserved_without_metre_guess(self):
        import struct
        data = bytearray(synthetic_layout())
        data[8:18] = struct.pack('>5H', 100, 200, 50, 300, 400)
        data[-1] = 1
        data.extend(struct.pack('>2H', 32768, 65535))
        data[18:22] = struct.pack('>I', len(data)-24)
        report = summarize_layout(decoder.decode_layout(bytes(data)))
        self.assertEqual(report['resolution_raw'], 50)
        self.assertEqual(report['origin_wire_u16'], (100, 200))
        self.assertEqual(report['rooms'][0]['polygon_vertices_wire_u16'], ((32768, 65535),))
        self.assertEqual(report['rooms'][0]['polygon_vertices_panel_xy'], [(3276.8, 0.1)])
        self.assertIsNone(report['rooms'][0]['area_m2'])
        self.assertFalse(report['rooms'][0]['polygon_coordinates_validated'])

    def test_invalid_grid_and_duplicate_or_out_of_range_table_rejected(self):
        for source in [SimpleNamespace(version=2,width=0,height=1,cells=b'',rooms=[]),
                       SimpleNamespace(version=2,width=3,height=1,cells=b'',rooms=[]),
                       layout([15,0,0], [room(1),room(1)]), layout([15,0,0],[room(28)]),
                       layout([15,0,0],[room(True)]), layout([15,0,0],[room(1,'X'*20)])]:
            with self.assertRaises(ValueError):
                summarize_layout(source)

    def run_cli(self, source, output, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = inspect_map.main(['--input', str(source), '--output-dir', str(output), *extra])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_writes_only_new_private_report_and_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input.bin'
            source.write_bytes(synthetic_layout()); source.chmod(0o600)
            code, stdout, stderr = self.run_cli(source, root/'result', '--source-kind', 'phone_cache')
            self.assertEqual((code, stderr), (0, ''))
            self.assertEqual(json.loads(stdout)['room_ids'], [1])
            report = json.loads((root/'result/rooms.json').read_bytes())
            self.assertEqual(report['source_kind'], 'phone_cache')
            self.assertFalse(report['download_performed'])
            self.assertNotIn('Room1', stdout)
            self.assertEqual(stat.S_IMODE((root/'result').stat().st_mode), 0o700)
            for name in ['rooms.json','map.png','room-ids.svg']:
                self.assertEqual(stat.S_IMODE((root/'result'/name).stat().st_mode), 0o600)
            self.assertEqual((root/'result/map.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
            code, _, _ = self.run_cli(source, root/'result')
            self.assertEqual(code, 1)
            self.assertTrue((root/'result/rooms.json').exists())

    def test_svg_embeds_png_and_only_numeric_labels_not_names_or_external_urls(self):
        import xml.etree.ElementTree as ET
        report = summarize_layout(layout([15,0,0,15,0,0], [room(1, '<script/>')]))
        image = b'synthetic-png'
        text = inspect_map.labeled_svg(image, report).decode()
        self.assertNotIn('<script', text)
        self.assertNotIn('http://192.', text)
        tree = ET.fromstring(text)
        label = tree.find('{http://www.w3.org/2000/svg}g/{http://www.w3.org/2000/svg}text')
        self.assertEqual(label.text, '1')
        flipped = ET.fromstring(inspect_map.labeled_svg(image, report, flip_y=True))
        other = flipped.find('{http://www.w3.org/2000/svg}g/{http://www.w3.org/2000/svg}text')
        self.assertNotEqual(label.attrib['y'], other.attrib['y'])

    def test_cli_rejects_public_symlink_and_invalid_inputs_without_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'PRIVATE_SECRET.bin'
            source.write_bytes(synthetic_layout()); source.chmod(0o644)
            for value in [source, root/'missing']:
                code, stdout, stderr = self.run_cli(value, root/'result')
                self.assertEqual((code, stdout), (1, ''))
                self.assertNotIn('PRIVATE_SECRET', stderr)
                self.assertFalse((root/'result').exists())
            source.chmod(0o600); link=root/'link.bin'; link.symlink_to(source)
            self.assertEqual(self.run_cli(link, root/'result')[0], 1)
            source.write_bytes(b'PRIVATE_SECRET'); source.chmod(0o600)
            self.assertEqual(self.run_cli(source, root/'result')[0], 1)

    def test_cli_no_socket_subprocess_cloud_or_cleaning_import(self):
        import ast
        for source in [Path(inspect_map.__file__), Path(inspect_map.__file__).parent/'conga8290/map_rooms.py']:
            tree = ast.parse(source.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for item in node.names:
                        self.assertNotIn(item.name.split('.')[0], {'socket','subprocess','requests','urllib','tinytuya'})
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or '').split('.')[0], {'socket','subprocess','requests','urllib','tinytuya'})

    def test_partial_output_failure_removes_only_new_invocation_outputs(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'input.bin'
            source.write_bytes(synthetic_layout()); source.chmod(0o600)
            original = inspect_map.write_private
            def write(path, data):
                if path.name == 'map.png':
                    raise OSError('PRIVATE_SECRET')
                original(path, data)
            with patch.object(inspect_map, 'write_private', write):
                code, stdout, stderr = self.run_cli(source, root/'new')
            self.assertEqual((code, stdout), (1, ''))
            self.assertNotIn('PRIVATE_SECRET', stderr)
            self.assertFalse((root/'new').exists())
            self.assertEqual(source.read_bytes(), synthetic_layout())
