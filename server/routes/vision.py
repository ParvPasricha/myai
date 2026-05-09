"""
Vision API routes:

    POST /vision/start            — start camera pipeline
    POST /vision/stop             — stop pipeline
    GET  /vision/status           — pipeline running state + stats
    POST /vision/frame            — analyze a single uploaded frame (JPEG bytes)
    POST /vision/enroll           — enroll a face from uploaded frame
    GET  /vision/faces            — list known enrolled faces
    GET  /vision/recognitions     — recent face recognition log
    GET  /vision/zones            — list configured zones
    POST /vision/zones            — set zones for a camera
    GET  /vision/items            — list all tracked item locations
    GET  /vision/item/{name}      — find where item was last seen
    GET  /vision/emotions         — recent emotion log
    GET  /vision/behavior         — behavioral pattern analysis
"""
import base64
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from server.auth import require_auth
from vision.camera_pipeline import (
    start_pipeline, stop_pipeline, is_running, get_stats,
    process_single_frame, frame_from_bytes,
)
from vision.face_recognition import (
    enroll_face, list_known_faces, get_recent_recognitions,
)
from vision.zone_mapper import get_zones, set_zones
from memory.structured import find_item_fuzzy, get_emotion_trend
from intelligence.behavior import analyze_emotion_patterns
from observability.logger import log

router = APIRouter()


# ── Pipeline control ──────────────────────────────────────────────────────────

class StartBody(BaseModel):
    source: str = "webcam"     # "webcam" | "rtsp://..." | device index as string
    camera_id: str = "default"
    fps: float = 2.0

@router.post("/vision/start")
async def start_vision(body: StartBody, _auth: dict = Depends(require_auth)):
    if is_running():
        return {"ok": False, "message": "Pipeline already running"}
    result = await start_pipeline(source=body.source, camera_id=body.camera_id, fps=body.fps)
    log.info("vision_pipeline_start_requested", source=body.source, fps=body.fps)
    return result


@router.post("/vision/stop")
async def stop_vision(_auth: dict = Depends(require_auth)):
    result = await stop_pipeline()
    log.info("vision_pipeline_stopped")
    return result


@router.get("/vision/status")
async def vision_status(_auth: dict = Depends(require_auth)):
    return {"running": is_running(), "stats": get_stats()}


# ── Single frame analysis ─────────────────────────────────────────────────────

@router.post("/vision/frame")
async def analyze_frame(file: UploadFile = File(...),
                        camera_id: str = "default",
                        _auth: dict = Depends(require_auth)):
    """Upload a JPEG/PNG frame and get full analysis: faces, emotions, items."""
    data = await file.read()
    frame = frame_from_bytes(data)
    if frame is None:
        raise HTTPException(status_code=400, detail="Could not decode image")
    result = await process_single_frame(frame, camera_id=camera_id)
    return result


# ── Face enrollment ───────────────────────────────────────────────────────────

@router.post("/vision/enroll")
async def enroll(name: str, file: UploadFile = File(...),
                 _auth: dict = Depends(require_auth)):
    """Enroll a face. Upload a photo, call multiple times for better accuracy."""
    data = await file.read()
    frame = frame_from_bytes(data)
    if frame is None:
        raise HTTPException(status_code=400, detail="Could not decode image")
    result = enroll_face(name, frame)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result.get("error"))
    log.info("face_enrolled", name=name, images=result.get("images_stored"))
    return result


@router.get("/vision/faces")
async def known_faces(_auth: dict = Depends(require_auth)):
    return {"faces": list_known_faces()}


@router.get("/vision/recognitions")
async def recent_recognitions(limit: int = 20, _auth: dict = Depends(require_auth)):
    return {"recognitions": get_recent_recognitions(limit)}


# ── Zone management ───────────────────────────────────────────────────────────

class ZoneBody(BaseModel):
    camera_id: str = "default"
    zones: list[dict]   # [{"name": "desk", "polygon": [[x,y],...]}]

@router.get("/vision/zones")
async def list_zones(camera_id: str = "default", _auth: dict = Depends(require_auth)):
    return {"camera_id": camera_id, "zones": get_zones(camera_id)}


@router.post("/vision/zones")
async def update_zones(body: ZoneBody, _auth: dict = Depends(require_auth)):
    set_zones(body.camera_id, body.zones)
    log.info("zones_updated", camera_id=body.camera_id, count=len(body.zones))
    return {"ok": True, "zones": len(body.zones)}


# ── Item queries ──────────────────────────────────────────────────────────────

@router.get("/vision/items")
async def all_items(_auth: dict = Depends(require_auth)):
    from memory.structured import find_item_fuzzy
    items = find_item_fuzzy("")   # empty query → all items
    return {"items": items}


@router.get("/vision/item/{name}")
async def find_item(name: str, _auth: dict = Depends(require_auth)):
    import time as _t
    items = find_item_fuzzy(name)
    if not items:
        return {"found": False, "query": name}
    best = items[0]
    age_h = round((_t.time() - best["last_seen"]) / 3600, 1)
    return {
        "found": True,
        "object": best["object_class"],
        "zone": best["zone_name"],
        "last_seen_hours_ago": age_h,
        "confidence": best["confidence"],
    }


# ── Emotion + behavior ────────────────────────────────────────────────────────

@router.get("/vision/emotions")
async def recent_emotions(hours: int = 24, _auth: dict = Depends(require_auth)):
    emotions = get_emotion_trend(hours=hours)
    return {"count": len(emotions), "emotions": emotions[-50:]}


@router.get("/vision/behavior")
async def behavior_analysis(hours: int = 72, _auth: dict = Depends(require_auth)):
    return analyze_emotion_patterns(hours=hours)
