"""Offline v2-to-cornguo MapData seam; no HA setup, transport or commands.

Pass the fork's existing MapData class as make_map_data. This avoids importing
HA, Pillow or tuya-vacuum just to test the Conga v2 adaptation. It deliberately
does not infer dock/robot positions, full trajectories or visual room order.
"""
import hashlib

from .map_cache_decoder import decode_layout, render_png


def render_v2_map(data, make_map_data, *, scale=4, flip_y=False):
    """Build the existing camera payload from bounded layout bytes only.

    The supplied factory is the reuse boundary, not a replacement HA entity.
    Orientation remains provisional. Callers must disable room controls and all
    write paths before using this seam in any later approved integration trial.
    """
    layout = decode_layout(data)
    png = render_png(layout, scale=scale, flip_y=flip_y)
    return make_map_data(
        image=png,
        rooms={room.room_id: room.name.rstrip('\0') or f'Room {room.room_id}'
               for room in layout.rooms},
        map_order=[],
        current_room=None,
        vacuum_position=None,
        image_id=hashlib.sha256(png).hexdigest()[:12],
    )
