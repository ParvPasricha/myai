"""
Voice Editor API.

GET  /voice-editor/config          — current voice config
PUT  /voice-editor/config          — update config (partial patch)
POST /voice-editor/preview         — synthesize a preview clip → MP3 bytes
POST /voice-editor/upload-reference — upload a WAV/MP3 clip to use as Jarvis voice reference
GET  /voice-editor/presets         — mood presets
POST /voice-editor/reset           — reset to defaults
"""
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from server.auth import require_auth
from observability.logger import log

router = APIRouter(prefix="/voice-editor")

_PREVIEW_TEXT = (
    "Initializing Jarvis. All systems online. "
    "How may I assist you today, sir?"
)


class ConfigPatch(BaseModel):
    engine: str | None = None
    chatterbox: dict | None = None
    edge: dict | None = None
    effects: dict | None = None


@router.get("/config")
async def get_voice_config(_auth: dict = Depends(require_auth)):
    from intelligence.voice_config import get_config, reference_clip_exists
    cfg = get_config()
    cfg["reference_clip_loaded"] = reference_clip_exists()
    return cfg


@router.put("/config")
async def update_voice_config(patch: ConfigPatch, _auth: dict = Depends(require_auth)):
    from intelligence.voice_config import update_config
    raw = patch.model_dump(exclude_none=True)
    updated = update_config(raw)
    log.info("voice_config_updated", patch=list(raw.keys()))
    return updated


@router.post("/preview")
async def preview_voice(
    body: dict | None = None,
    _auth: dict = Depends(require_auth),
):
    """Generate a short preview clip with current (or overridden) settings."""
    from intelligence.voice_config import get_config, update_config
    from intelligence.voice_cloner import synthesize
    from intelligence.voice_effects import apply_effects, numpy_to_mp3_bytes

    text = (body or {}).get("text", _PREVIEW_TEXT)
    # allow temporary override for live preview without saving
    override = (body or {}).get("effects_override")

    cfg = get_config()
    if override:
        import copy
        cfg = copy.deepcopy(cfg)
        cfg.setdefault("effects", {}).update(override)

    audio, sr = await __import__("asyncio").to_thread(synthesize, text, cfg)
    audio      = apply_effects(audio, sr, cfg)
    mp3_bytes  = numpy_to_mp3_bytes(audio, sr)

    log.info("voice_preview_generated", bytes=len(mp3_bytes))
    return Response(
        content=mp3_bytes,
        media_type="audio/mpeg",
        headers={"X-Preview-Length-Chars": str(len(text))},
    )


@router.post("/upload-reference")
async def upload_reference(
    file: UploadFile = File(...),
    _auth: dict = Depends(require_auth),
):
    """
    Upload a WAV or MP3 audio clip to use as the Jarvis voice reference.
    Saves to models/jarvis_voice/reference.wav (converts MP3→WAV if needed).
    """
    from intelligence.voice_config import reference_clip_path

    dest = reference_clip_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "clip.wav").suffix.lower()

    # write upload to temp
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(await file.read())
        tmp_path = f.name

    try:
        if suffix == ".mp3":
            from pydub import AudioSegment
            seg = AudioSegment.from_mp3(tmp_path).set_channels(1).set_frame_rate(22050)
            seg.export(str(dest), format="wav")
        else:
            shutil.copy(tmp_path, dest)

        size_mb = dest.stat().st_size / 1_000_000
        log.info("voice_reference_uploaded", size_mb=round(size_mb, 2))
        return {"status": "ok", "path": str(dest), "size_mb": round(size_mb, 2)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.get("/presets")
async def get_presets(_auth: dict = Depends(require_auth)):
    from intelligence.voice_config import get_mood_presets
    return get_mood_presets()


@router.post("/reset")
async def reset_config(_auth: dict = Depends(require_auth)):
    from intelligence.voice_config import _DEFAULTS, _save
    _save(_DEFAULTS.copy())
    log.info("voice_config_reset")
    return {"status": "reset", "config": _DEFAULTS}
