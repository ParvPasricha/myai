"""
Camera Pipeline — orchestrates face recognition, emotion tracking, and item tracking.

Sources supported:
    "webcam"        → cv2.VideoCapture(0)   (Mac dev)
    "rtsp://..."    → RTSP stream           (production IP cameras)
    int             → specific device index

Pipeline runs as an asyncio background task.
Start/stop via POST /vision/start and POST /vision/stop.
"""
import asyncio
import time
from typing import Optional

import cv2
import numpy as np

from vision.face_recognition import detect_faces, identify_face
from vision.emotion_tracker import process_and_log
from vision.item_tracker import get_tracker
from observability.logger import log
from observability.metrics import brain_state_focus

_running = False
_pipeline_task: Optional[asyncio.Task] = None
_pipeline_lock = asyncio.Lock()
_stats = {
    "frames_processed": 0,
    "faces_detected": 0,
    "items_tracked": 0,
    "emotions_logged": 0,
    "started_at": None,
    "last_frame_at": None,
}


def is_running() -> bool:
    return _running


def get_stats() -> dict:
    return dict(_stats)


async def start_pipeline(source: str = "webcam", camera_id: str = "default",
                         fps: float = 2.0):
    """Start the camera pipeline as a background asyncio task."""
    global _pipeline_task, _running
    async with _pipeline_lock:
        if _running:
            return {"ok": False, "error": "Pipeline already running"}
        _pipeline_task = asyncio.create_task(
            _run(source=source, camera_id=camera_id, fps=fps)
        )
    return {"ok": True, "source": source, "fps": fps}


async def stop_pipeline():
    """Stop the running pipeline."""
    global _running, _pipeline_task
    async with _pipeline_lock:
        _running = False
        if _pipeline_task:
            _pipeline_task.cancel()
            try:
                await _pipeline_task
            except (asyncio.CancelledError, Exception):
                pass
            _pipeline_task = None
    return {"ok": True, "stats": _stats}


async def process_single_frame(frame: np.ndarray,
                                camera_id: str = "default") -> dict:
    """
    Process one frame through the full pipeline.
    Returns a summary of what was detected.
    Used by the test endpoint and single-frame API.
    """
    summary = {"faces": [], "emotions": [], "items": []}

    # Face detection + recognition
    face_boxes = detect_faces(frame)
    for (x1, y1, x2, y2) in face_boxes:
        identity = identify_face(frame, x1, y1, x2, y2, camera_id)
        face_crop = frame[y1:y2, x1:x2]

        emotion_result = {}
        if face_crop.size > 0:
            emotion_result = process_and_log(face_crop, source="camera",
                                             publish_mqtt=True)
            summary["emotions"].append(emotion_result)

        summary["faces"].append({**identity, **emotion_result,
                                  "bbox": [x1, y1, x2, y2]})

        if identity["known"]:
            try:
                from server.main import mqtt_publish
                import json
                mqtt_publish("parv/camera/face_recognized", json.dumps({
                    "name": identity["name"],
                    "confidence": identity["confidence"],
                    "camera_id": camera_id,
                }))
            except Exception:
                pass

    # Item tracking
    tracker = get_tracker(camera_id)
    items = tracker.process_frame(frame)
    summary["items"] = items

    return summary


async def _run(source: str, camera_id: str, fps: float):
    global _running, _stats
    _running = True
    _stats = {"frames_processed": 0, "faces_detected": 0, "items_tracked": 0,
              "emotions_logged": 0, "started_at": time.time(), "last_frame_at": None}

    device = 0 if source == "webcam" else source
    cap = cv2.VideoCapture(device)

    if not cap.isOpened():
        log.error("camera_open_failed", source=source)
        _running = False
        return

    log.info("camera_pipeline_started", source=source, fps=fps, camera_id=camera_id)
    interval = 1.0 / fps

    try:
        while _running:
            t0 = time.time()
            ret, frame = cap.read()
            if not ret:
                log.warn("camera_frame_read_failed", source=source)
                await asyncio.sleep(1.0)
                continue

            await process_single_frame(frame, camera_id)

            _stats["frames_processed"] += 1
            _stats["last_frame_at"] = time.time()

            elapsed = time.time() - t0
            sleep_time = max(0, interval - elapsed)
            await asyncio.sleep(sleep_time)

    except asyncio.CancelledError:
        pass
    finally:
        cap.release()
        _running = False
        log.info("camera_pipeline_stopped", frames=_stats["frames_processed"])


def frame_from_webcam() -> Optional[np.ndarray]:
    """Capture a single frame from the webcam. Used for one-shot enrollment/testing."""
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return None
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def frame_from_bytes(data: bytes) -> Optional[np.ndarray]:
    """Decode a JPEG/PNG image from bytes (for API uploads)."""
    arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)
