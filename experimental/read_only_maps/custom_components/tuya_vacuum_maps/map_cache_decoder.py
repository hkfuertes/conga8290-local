"""Offline research decoder for the observed Tuya v2 layout cache.

Format reconstructed from the robot panel's modules 1836/1837 (static evidence
ev_8e73f1386cc88ca74230fbc228b0cda1d7b225665d67c2d4e28553ac17022858).
No JavaScript, Android code, network request or robot command is executed.
The output is private; orientation and physical coordinate alignment need review.
"""
import argparse
import binascii
from dataclasses import dataclass
import json
import os
from pathlib import Path
import struct
import zlib


MAX_INPUT = 8_000_000
MAX_DECODED = 8_000_000
MAX_CELLS = 1_000_000
MAX_DIMENSION = 2048
MAX_RENDER_PIXELS = 4_000_000
ROOM_COLORS = (
    (253, 228, 207), (142, 236, 245), (207, 186, 240), (241, 192, 232),
    (163, 196, 243), (152, 245, 225), (255, 207, 210), (144, 219, 244),
    (225, 193, 235), (142, 204, 245), (237, 221, 222), (163, 184, 243),
    (239, 207, 225), (178, 242, 190), (174, 230, 248), (144, 194, 244),
)


class MapFormatError(ValueError):
    """A bounded format error without private map contents."""


def decompress_lz4_block(source, expected_size):
    """Decode a raw LZ4 block, bounding every literal and overlapping match."""
    if not 0 < expected_size <= MAX_DECODED:
        raise MapFormatError('Invalid decompressed size')
    if not source:
        raise MapFormatError('Empty LZ4 block')
    result = bytearray()
    position = 0

    def length(base):
        nonlocal position
        total = base
        if base == 15:
            while True:
                if position >= len(source):
                    raise MapFormatError('Truncated LZ4 length')
                part = source[position]
                position += 1
                total += part
                if total > expected_size:
                    raise MapFormatError('LZ4 length exceeds output bound')
                if part != 255:
                    break
        return total

    while position < len(source):
        token = source[position]
        position += 1
        literal_count = length(token >> 4)
        if position + literal_count > len(source):
            raise MapFormatError('Truncated LZ4 literals')
        if len(result) + literal_count > expected_size:
            raise MapFormatError('LZ4 literals exceed output bound')
        result.extend(source[position:position + literal_count])
        position += literal_count
        if position == len(source):
            if token & 15:
                raise MapFormatError('Incomplete final LZ4 sequence')
            break
        if position + 2 > len(source):
            raise MapFormatError('Truncated LZ4 offset')
        offset = int.from_bytes(source[position:position + 2], 'little')
        position += 2
        if not 0 < offset <= len(result):
            raise MapFormatError('Invalid LZ4 back-reference')
        match_count = length(token & 15) + 4
        if len(result) + match_count > expected_size:
            raise MapFormatError('LZ4 match exceeds output bound')
        for _ in range(match_count):
            result.append(result[-offset])
    if len(result) != expected_size:
        raise MapFormatError('Decompressed length does not match header')
    return bytes(result)


@dataclass(frozen=True)
class Room:
    room_id: int
    order: int
    sweep_count: int
    mop_count: int
    name: str
    vertex_count: int
    vertices_wire_u16: tuple[tuple[int, int], ...] = ()
    sweep_forbidden_raw: int | None = None
    mop_forbidden_raw: int | None = None
    fan_raw: int | None = None
    water_raw: int | None = None
    y_mode_raw: int | None = None


@dataclass(frozen=True)
class Layout:
    version: int
    width: int
    height: int
    cells: bytes
    rooms: tuple[Room, ...]
    map_id: int | None = None
    resolution_raw: int | None = None
    origin_wire_u16: tuple[int, int] | None = None
    dock_wire_u16: tuple[int, int] | None = None


@dataclass(frozen=True)
class PathStream:
    """Wire coordinates only: not aligned to image or physical coordinates."""
    version: int
    path_type: int
    total_count: int
    points: tuple[tuple[int, int], ...]


def decode_path(data):
    """Parse the observed 13-byte v0 path header and bounded point records.

    Type 2 is incremental; this function does not invent missing earlier points
    or accumulate updates. No path-to-grid coordinate transformation is applied.
    """
    if not 13 <= len(data) <= MAX_INPUT:
        raise MapFormatError('Path file size is out of bounds')
    if data[0] != 0 or data[4] not in (1, 2, 3):
        raise MapFormatError('Unsupported path version or type')
    total_count = int.from_bytes(data[5:9], 'big')
    if not 0 <= total_count <= MAX_CELLS:
        raise MapFormatError('Path point count is out of bounds')
    compressed_size = int.from_bytes(data[11:13], 'big')
    body = data[13:]
    if compressed_size:
        if len(body) != compressed_size:
            raise MapFormatError('Compressed path size does not match header')
        body = decompress_lz4_block(body, total_count * 4)
    if len(body) % 4:
        raise MapFormatError('Truncated path point')
    point_count = len(body) // 4
    if point_count > total_count or (data[4] == 1 and point_count != total_count):
        raise MapFormatError('Path point count does not match header')
    points = tuple(struct.iter_unpack('>2H', body))
    return PathStream(0, data[4], total_count, points)


def decode_layout(data):
    if not 24 <= len(data) <= MAX_INPUT:
        raise MapFormatError('Layout file size is out of bounds')
    if data[0] != 2:
        raise MapFormatError('This research decoder supports map version 2 only')
    header = struct.unpack('>12H', data[:24])
    width, height = header[2:4]
    cells = width * height
    if (not 0 < width <= MAX_DIMENSION or not 0 < height <= MAX_DIMENSION
            or cells > MAX_CELLS):
        raise MapFormatError('Map dimensions are out of bounds')
    decoded_size = int.from_bytes(data[18:22], 'big')
    if not cells + 2 <= decoded_size <= MAX_DECODED:
        raise MapFormatError('Invalid layout body size')
    compressed_size = header[11]
    body = data[24:]
    if compressed_size:
        if len(body) != compressed_size:
            raise MapFormatError('Compressed body size does not match header')
        body = decompress_lz4_block(body, decoded_size)
    elif len(body) != decoded_size:
        raise MapFormatError('Uncompressed body size does not match header')
    table = body[cells:]
    room_count = table[1]
    if room_count > 28:
        raise MapFormatError('Too many v2 room records')
    position = 2
    rooms = []
    for _ in range(room_count):
        if position + 47 > len(table):
            raise MapFormatError('Truncated room record')
        record = table[position:position + 47]
        room_id, order, sweep_count, mop_count = struct.unpack('>4H', record[:8])
        if room_id >= 28 or any(room.room_id == room_id for room in rooms):
            raise MapFormatError('Invalid or duplicated v2 room ID')
        name_size = record[26]
        if name_size > 19:
            raise MapFormatError('Room name exceeds fixed field')
        try:
            name = record[27:27 + name_size].decode('utf-8')
        except UnicodeDecodeError as error:
            raise MapFormatError('Invalid room-name encoding') from error
        vertex_count = record[46]
        end = position + 47 + vertex_count * 4
        if end > len(table):
            raise MapFormatError('Truncated room polygon')
        # Unsigned wire coordinates only; neither grid nor physical transforms.
        vertices = tuple(struct.iter_unpack('>HH', table[position + 47:end]))
        rooms.append(Room(room_id, order, sweep_count, mop_count, name, vertex_count,
                          vertices, *record[9:14]))
        position = end
    if position != len(table):
        raise MapFormatError('Unexpected trailing room-table data')
    return Layout(2, width, height, body[:cells], tuple(rooms),
                  int.from_bytes(data[1:3], 'big'), header[6],
                  tuple(header[4:6]), tuple(header[7:9]))


def cell_color(value):
    """The low three bits are pixel type; the upper five bits are room ID."""
    pixel_type = value & 7
    room_id = value >> 3
    if pixel_type == 1:
        return (50, 50, 50)  # Obstacle/wall.
    if pixel_type in (2, 7):
        color = ROOM_COLORS[room_id % len(ROOM_COLORS)] if room_id < 28 else (190, 190, 190)
        if pixel_type == 2:
            return tuple(component * 3 // 4 for component in color)  # Carpet.
        return color
    return (20, 25, 30)  # Unknown / unsupported pixel type.


def render_png(layout, scale=4, flip_y=False):
    if not 1 <= scale <= 8:
        raise MapFormatError('Scale must be between 1 and 8')
    width, height = layout.width * scale, layout.height * scale
    if width * height > MAX_RENDER_PIXELS:
        raise MapFormatError('Rendered image exceeds pixel bound')
    rows = []
    indices = range(layout.height - 1, -1, -1) if flip_y else range(layout.height)
    for row_index in indices:
        row = layout.cells[row_index * layout.width:(row_index + 1) * layout.width]
        pixels = b''.join(bytes(cell_color(value)) * scale for value in row)
        rows.extend([b'\x00' + pixels] * scale)

    def chunk(kind, content):
        return (struct.pack('>I', len(content)) + kind + content
                + struct.pack('>I', binascii.crc32(kind + content) & 0xffffffff))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>2I5B', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows)))
            + chunk(b'IEND', b''))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='Private map.bin.stream copy')
    parser.add_argument('--output', required=True, type=Path, help='New private PNG; never overwritten')
    parser.add_argument('--scale', type=int, default=4)
    parser.add_argument('--flip-y', action='store_true', help='Flip rows for visual alignment review')
    parser.add_argument('--path-input', type=Path, help='Optional private cleanPath.bin.stream copy')
    args = parser.parse_args()
    try:
        with args.input.open('rb') as handle:
            data = handle.read(MAX_INPUT + 1)
        layout = decode_layout(data)
        path = None
        if args.path_input:
            with args.path_input.open('rb') as handle:
                path = decode_path(handle.read(MAX_INPUT + 1))
        image = render_png(layout, args.scale, args.flip_y)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(image)
    except (MapFormatError, OSError) as error:
        # Do not include exception details that may contain private paths/data.
        parser.exit(1, f'Offline map decoding failed: {type(error).__name__}\n')
    print(json.dumps({'decoded_version': layout.version, 'room_count': len(layout.rooms),
                      'source_cells': [layout.width, layout.height], 'private_png': str(args.output),
                      'file_mode': '0600', 'trajectory_decoded': False,
                      'path_wire_points_parsed': len(path.points) if path else None,
                      'path_incremental': path.path_type == 2 if path else None,
                      'orientation_validated': False, 'network_requests': 0,
                      'robot_commands': 0}))


if __name__ == '__main__':
    main()
