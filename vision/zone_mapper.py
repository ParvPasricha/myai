"""
Zone Mapper — defines named regions in the camera frame.

A zone is a named polygon (e.g. "desk", "shelf", "couch", "door").
Zones are calibrated once by saving reference frame coordinates.
Objects detected inside a zone's polygon are tagged with that zone name.

Zones stored in memory/zones.json (per camera_id).
"""
import json
import time
from pathlib import Path
from typing import Optional

import numpy as np

_ZONES_FILE = Path(__file__).parent.parent / "memory" / "zones.json"
_ZONES_FILE.parent.mkdir(exist_ok=True)

# In-memory cache
_zones: dict[str, list[dict]] = {}   # camera_id → list of {name, polygon}


def _load():
    global _zones
    if _ZONES_FILE.exists():
        _zones = json.loads(_ZONES_FILE.read_text())


def _save():
    _ZONES_FILE.write_text(json.dumps(_zones, indent=2))


_load()


def set_zones(camera_id: str, zones: list[dict]):
    """
    Save zones for a camera.
    zones: [{"name": "desk", "polygon": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]}, ...]
    Polygon points are pixel coordinates in the camera's reference frame.
    """
    _zones[camera_id] = zones
    _save()


def get_zones(camera_id: str) -> list[dict]:
    return _zones.get(camera_id, [])


def point_in_zone(x: float, y: float, camera_id: str) -> Optional[str]:
    """
    Return the name of the zone containing point (x, y), or None.
    Uses ray-casting algorithm for polygon containment.
    """
    for zone in _zones.get(camera_id, []):
        polygon = np.array(zone["polygon"], dtype=np.float32)
        if _point_in_polygon(x, y, polygon):
            return zone["name"]
    return None


def bbox_zone(x1: float, y1: float, x2: float, y2: float, camera_id: str) -> Optional[str]:
    """Return zone for the centre-bottom of a bounding box (best for objects on surfaces)."""
    cx = (x1 + x2) / 2
    cy = y2   # bottom centre — where the object sits
    return point_in_zone(cx, cy, camera_id)


def _point_in_polygon(x: float, y: float, polygon: np.ndarray) -> bool:
    n = len(polygon)
    inside = False
    px, py = x, y
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def default_zones(width: int = 640, height: int = 480) -> list[dict]:
    """
    Generate sensible default zones for a single camera view.
    Divides the frame into 4 quadrant zones.
    Useful when no manual calibration has been done.
    """
    w, h = width, height
    return [
        {"name": "desk",   "polygon": [[0, 0], [w//2, 0], [w//2, h//2], [0, h//2]]},
        {"name": "shelf",  "polygon": [[w//2, 0], [w, 0], [w, h//2], [w//2, h//2]]},
        {"name": "floor_left",  "polygon": [[0, h//2], [w//2, h//2], [w//2, h], [0, h]]},
        {"name": "floor_right", "polygon": [[w//2, h//2], [w, h//2], [w, h], [w//2, h]]},
    ]
