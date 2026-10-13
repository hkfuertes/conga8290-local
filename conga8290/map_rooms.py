"""Offline room-ID/raster-area projection; no network, credentials or controls.

Areas are floor/carpet cell counts, not measured square metres. Coordinates refer
to the decoded grid, not physical coordinates or accepted cleaning-command IDs.
"""


def summarize_layout(layout):
    if (layout.version != 2 or type(layout.width) is not int or type(layout.height) is not int
            or not 0 < layout.width <= 2048 or not 0 < layout.height <= 2048
            or layout.width * layout.height > 1_000_000
            or not isinstance(layout.cells, bytes) or len(layout.cells) != layout.width * layout.height):
        raise ValueError('bounded_v2_layout_required')
    declared = {}
    for room in layout.rooms:
        vertices = getattr(room, 'vertices_wire_u16', ())
        if (type(room.room_id) is not int or not 0 <= room.room_id < 28
                or room.room_id in declared or not isinstance(room.name, str)
                or len(room.name.encode('utf-8')) > 19
                or type(room.vertex_count) is not int or not 0 <= room.vertex_count <= 255
                or not isinstance(vertices, tuple) or len(vertices) != room.vertex_count
                or any(not isinstance(point, tuple) or len(point) != 2
                       or any(type(value) is not int or not 0 <= value <= 65535 for value in point)
                       for point in vertices)):
            raise ValueError('bounded_unique_room_table_required')
        declared[room.room_id] = room
    segments = {}
    floor_total = unassigned = 0
    for index, value in enumerate(layout.cells):
        kind, identifier = value & 7, value >> 3
        if kind not in {2, 7}:
            continue
        floor_total += 1
        if identifier >= 28:
            unassigned += 1
            continue
        x, y = index % layout.width, index // layout.width
        row = segments.setdefault(identifier, dict(cells=0, carpet=0, sx=0, sy=0,
            xmin=x, xmax=x, ymin=y, ymax=y))
        row['cells'] += 1
        row['carpet'] += kind == 2
        row['sx'] += x
        row['sy'] += y
        row['xmin'], row['xmax'] = min(row['xmin'], x), max(row['xmax'], x)
        row['ymin'], row['ymax'] = min(row['ymin'], y), max(row['ymax'], y)
    # Select an actual member cell nearest the raster centroid, even for concave
    # or disconnected rooms. Integer distances avoid coordinate/rounding guesses.
    labels = {}
    for index, value in enumerate(layout.cells):
        identifier = value >> 3
        if value & 7 not in {2, 7} or identifier not in segments:
            continue
        row = segments[identifier]
        x, y = index % layout.width, index // layout.width
        distance = (x * row['cells'] - row['sx'])**2 + (y * row['cells'] - row['sy'])**2
        if identifier not in labels or distance < labels[identifier][0]:
            labels[identifier] = distance, [x, y]
    rooms = []
    for identifier, room in sorted(declared.items()):
        row = segments.get(identifier)
        wire_vertices = getattr(room, 'vertices_wire_u16', ())
        # Source-proven panel transform, not an inferred physical/grid transform.
        def panel_word(value):
            return (value-65536 if value > 32768 else value) / 10
        panel_vertices = list(dict.fromkeys((panel_word(x), -panel_word(y)) for x, y in wire_vertices))
        rooms.append(dict(room_id=identifier, name=room.name.rstrip('\0'), order=room.order,
            sweep_count=room.sweep_count, mop_count=room.mop_count,
            area_cells=row['cells'] if row else 0,
            floor_cells=row['cells']-row['carpet'] if row else 0,
            carpet_cells=row['carpet'] if row else 0, area_m2=None,
            bounds_grid_xy=[row['xmin'], row['ymin'], row['xmax'], row['ymax']] if row else None,
            label_grid_xy=labels[identifier][1] if row else None,
            polygon_vertex_count=room.vertex_count,
            polygon_vertices_wire_u16=wire_vertices,
            polygon_vertices_panel_xy=panel_vertices,
            polygon_panel_transform='dealPL_gt32768_then_x_div10_y_neg_div10_deduplicated',
            polygon_coordinates_validated=False,
            floor_pixel_hex=f'{(identifier << 3) | 7:02x}',
            carpet_pixel_hex=f'{(identifier << 3) | 2:02x}',
            cleaning_options_raw={field: getattr(room, field+'_raw', None)
                for field in ['sweep_forbidden', 'mop_forbidden', 'fan', 'water', 'y_mode']}))
    return dict(map_version=2, map_id=getattr(layout, 'map_id', None),
        resolution_raw=getattr(layout, 'resolution_raw', None),
        origin_wire_u16=getattr(layout, 'origin_wire_u16', None),
        dock_wire_u16=getattr(layout, 'dock_wire_u16', None),
        grid_size=[layout.width, layout.height], rooms=rooms,
        segmented_room_ids=sorted(segments), unlisted_segment_ids=sorted(set(segments)-set(declared)),
        floor_cells=floor_total, unassigned_floor_cells=unassigned,
        area_basis='raster_floor_and_carpet_cells', metric_scale_validated=False,
        coordinates='decoded_grid_xy_rows_not_physical', orientation_validated=False,
        command_ids_validated=False, freshness='unknown', robot_commands=0)
