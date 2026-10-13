#!/usr/bin/env python3
"""Inspect an existing private v2 map: room IDs, raster areas and PNG preview.

Offline only: does not download/refresh a map, connect to a robot or clean. Room
IDs are map records, not validated control IDs. Output contains private floor-plan
data; keep it out of repositories/cloud sync. No authentication is needed.
"""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

from conga8290.map_rooms import summarize_layout


def decoder_module():
    # Reuse the existing tested v2 renderer without importing Home Assistant or
    # executing the integration's __init__ / any proprietary SDK.
    source = Path(__file__).resolve().parent / 'experimental/read_only_maps/custom_components/tuya_vacuum_maps/map_cache_decoder.py'
    name = '_conga8290_offline_map_decoder'
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_private_map(path, maximum):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or not 24 <= info.st_size <= maximum):
            raise ValueError('owned_regular_private_map_required')
        data = handle.read(maximum + 1)
    if len(data) != info.st_size:
        raise ValueError('map_changed_or_input_budget_exceeded')
    return data


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)


def labeled_svg(image, report, *, scale=4, flip_y=False):
    """Static embedded PNG + numeric labels. No scripts, URLs or room-name markup."""
    width, height = (value*scale for value in report['grid_size'])
    background = base64.b64encode(image).decode('ascii')
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<title>Cached/imported map room IDs; orientation and control IDs unvalidated</title>',
             f'<image width="{width}" height="{height}" href="data:image/png;base64,{background}"/>',
             '<g font-family="sans-serif" font-size="20" font-weight="bold" text-anchor="middle" fill="white" stroke="black" stroke-width="4" paint-order="stroke">']
    for room in report['rooms']:
        if room['label_grid_xy'] is None:
            continue
        x, y = room['label_grid_xy']
        if flip_y:
            y = report['grid_size'][1]-1-y
        parts.append(f'<text x="{(x+.5)*scale:g}" y="{(y+.5)*scale:g}" dominant-baseline="middle">{room["room_id"]}</text>')
    return ('\n'.join(parts+['</g>', '</svg>'])+'\n').encode('ascii')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='Existing private v2 map.bin or map.bin.stream (0600)')
    parser.add_argument('--output-dir', required=True, type=Path, help='New private directory; never overwrite an existing one')
    parser.add_argument('--source-kind', choices=['user_file', 'phone_cache', 'history_snapshot'], default='user_file',
                        help='Declared provenance; freshness always remains unknown')
    parser.add_argument('--flip-y', action='store_true', help='Flip preview rows for review, not physical validation')
    args = parser.parse_args(argv)
    created = False
    try:
        decoder = decoder_module()
        data = read_private_map(args.input, decoder.MAX_INPUT)
        layout = decoder.decode_layout(data)
        report = summarize_layout(layout)
        report.update(source_kind=args.source_kind, source_kind_basis='user_declared',
                      download_performed=False, preview_flip_y=args.flip_y)
        image = decoder.render_png(layout, scale=4, flip_y=args.flip_y)
        annotated = labeled_svg(image, report, flip_y=args.flip_y)
        args.output_dir.mkdir(mode=0o700)  # Exclusive; no recursive/public parents.
        created = True
        write_private(args.output_dir / 'rooms.json', (json.dumps(report, ensure_ascii=True, indent=2)+'\n').encode())
        write_private(args.output_dir / 'map.png', image)
        write_private(args.output_dir / 'room-ids.svg', annotated)
    except Exception as error:
        if created:
            # Only files inside the directory this invocation created. Existing
            # user files/permission bits are never overwritten or changed.
            for name in ['rooms.json', 'map.png', 'room-ids.svg']:
                try:
                    (args.output_dir / name).unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                args.output_dir.rmdir()
            except OSError:
                pass
        print(json.dumps(dict(status='stopped', failure_type=type(error).__name__,
                              private_details_suppressed=True, robot_commands=0)), file=sys.stderr)
        return 1
    print(json.dumps(dict(status='decoded', room_count=len(report['rooms']),
        room_ids=[room['room_id'] for room in report['rooms']],
        source_kind=args.source_kind, freshness='unknown', area_units='cells',
        metric_scale_validated=False, command_ids_validated=False,
        private_output_dir=str(args.output_dir), download_performed=False, robot_commands=0)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
