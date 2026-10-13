from dataclasses import dataclass

@dataclass
class MapData:
    """The latest map of the vacuum."""
    image: bytes
    rooms: dict[int, str]
    map_order: list[int]
    current_room: int | None = None
    vacuum_position: tuple[float, float] | None = None
    image_id: str = ''
