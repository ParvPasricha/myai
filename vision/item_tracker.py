"""
Item Tracker — detects and tracks household objects using YOLOv11n.

Pipeline:
    frame → YOLO detection → bbox zone lookup → upsert item_sightings DB

YOLO detects 80 COCO classes. We filter to "trackable" household items
and map them to zones using zone_mapper.py polygons.

Item memory is stored in memory/structured.py (item_sightings table).
Natural language queries like "where are my keys?" use find_item_fuzzy().
"""
import time
from pathlib import Path
from typing import Optional

import numpy as np

from vision.zone_mapper import bbox_zone, default_zones, get_zones, set_zones
from memory.structured import upsert_item_sighting
from observability.logger import log

# COCO classes worth tracking as household items
# Maps YOLO class name → friendly name stored in DB
_TRACKABLE: dict[str, str] = {
    "backpack": "backpack",
    "umbrella": "umbrella",
    "handbag": "bag",
    "tie": "tie",
    "suitcase": "suitcase",
    "bottle": "bottle",
    "wine glass": "glass",
    "cup": "cup",
    "fork": "fork",
    "knife": "knife",
    "spoon": "spoon",
    "bowl": "bowl",
    "banana": "banana",
    "apple": "apple",
    "sandwich": "sandwich",
    "orange": "orange",
    "book": "book",
    "clock": "clock",
    "vase": "vase",
    "scissors": "scissors",
    "teddy bear": "teddy bear",
    "hair drier": "hair dryer",
    "toothbrush": "toothbrush",
    "laptop": "laptop",
    "mouse": "mouse",
    "remote": "remote",
    "keyboard": "keyboard",
    "cell phone": "phone",
    "microwave": "microwave",
    "oven": "oven",
    "toaster": "toaster",
    "sink": "sink",
    "refrigerator": "fridge",
    "tv": "tv",
    "chair": "chair",
    "couch": "couch",
    "potted plant": "plant",
    "bed": "bed",
    "dining table": "table",
}

# Confidence threshold for YOLO detections
_MIN_CONFIDENCE = 0.45


class ItemTracker:
    def __init__(self, camera_id: str = "default"):
        self.camera_id = camera_id
        self._model = None
        self._frame_count = 0
        self._process_every = 5   # process every Nth frame (CPU efficiency)

    def _get_model(self):
        if self._model is None:
            from ultralytics import YOLO
            self._model = YOLO("yolo11n.pt")
        return self._model

    def _ensure_zones(self, frame_shape):
        """Set default zones if none configured."""
        if not get_zones(self.camera_id):
            h, w = frame_shape[:2]
            set_zones(self.camera_id, default_zones(w, h))

    def process_frame(self, frame: np.ndarray) -> list[dict]:
        """
        Run YOLO on frame, map detections to zones, upsert item_sightings.
        Returns list of detected+tracked items.
        Skips non-trackable frames for CPU efficiency.
        """
        self._frame_count += 1
        if self._frame_count % self._process_every != 0:
            return []

        self._ensure_zones(frame.shape)
        model = self._get_model()

        results = model(frame, verbose=False, conf=_MIN_CONFIDENCE)
        tracked = []

        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                cls_name = model.names[cls_id]
                conf = float(box.conf[0])

                if cls_name not in _TRACKABLE:
                    continue

                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
                friendly_name = _TRACKABLE[cls_name]
                zone = bbox_zone(x1, y1, x2, y2, self.camera_id) or "unknown"

                upsert_item_sighting(
                    object_class=friendly_name,
                    zone_name=zone,
                    camera_id=self.camera_id,
                    confidence=conf,
                )

                try:
                    from server.main import mqtt_publish
                    import json
                    mqtt_publish("parv/item/seen", json.dumps({
                        "object": friendly_name,
                        "zone": zone,
                        "confidence": round(conf, 3),
                    }))
                except Exception:
                    pass

                tracked.append({
                    "object": friendly_name,
                    "zone": zone,
                    "confidence": round(conf, 3),
                    "bbox": [x1, y1, x2, y2],
                })

        if tracked:
            log.debug("items_tracked", count=len(tracked),
                      items=[t["object"] for t in tracked])

        return tracked


# Per-camera tracker registry — prevents YOLO model GC leak on camera_id change
_trackers: dict[str, "ItemTracker"] = {}


def get_tracker(camera_id: str = "default") -> "ItemTracker":
    if camera_id not in _trackers:
        _trackers[camera_id] = ItemTracker(camera_id)
    return _trackers[camera_id]
