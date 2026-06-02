"""
Voice configuration — persisted to models/jarvis_voice/config.json.

Loaded once at import time; callers use get/set helpers.
"""
import json
from pathlib import Path

_CONFIG_PATH    = Path(__file__).parent.parent / "models" / "jarvis_voice" / "config.json"
_REFERENCE_CLIP = Path(__file__).parent.parent / "models" / "jarvis_voice" / "reference.wav"


_DEFAULTS = {
    "engine": "chatterbox",
    "reference_clip": str(_REFERENCE_CLIP),   # always the JARVIS sample
    "chatterbox": {
        "exaggeration": 0.50,
        "cfg_weight": 0.75,          # higher adherence to reference clip
    },
    "edge": {
        "voice": "en-GB-RyanNeural",
        "rate": "-5%",
        "pitch": "-10Hz",
    },
    "effects": {
        "robotic": 0,                # 0–100: ring modulator depth
        "warmth": 0,                 # 0–100: reverb + low-shelf EQ (0=clean/dry)
        "emotion_intensity": 100,    # 0–100: dynamic range (100=wide/natural, no compression)
        "pitch_shift": 0,            # semitones: -6 to +6
        "tempo": 1.0,                # 0.75–1.5×
        "mood": "serious",           # "calm" | "serious" | "urgent" | "cheerful"
    },
}

_MOOD_PRESETS = {
    "calm":      {"pitch_shift": -1, "tempo": 0.92, "emotion_intensity": 30},
    "serious":   {"pitch_shift":  0, "tempo": 0.97, "emotion_intensity": 50},
    "urgent":    {"pitch_shift":  1, "tempo": 1.10, "emotion_intensity": 75},
    "cheerful":  {"pitch_shift":  2, "tempo": 1.05, "emotion_intensity": 65},
}


def _load() -> dict:
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text())
        except Exception:
            pass
    return _DEFAULTS.copy()


def _save(cfg: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def get_config() -> dict:
    return _load()


def update_config(patch: dict) -> dict:
    cfg = _load()
    # deep-merge effects sub-dict
    if "effects" in patch and isinstance(patch["effects"], dict):
        cfg.setdefault("effects", {}).update(patch["effects"])
        del patch["effects"]
    if "chatterbox" in patch and isinstance(patch["chatterbox"], dict):
        cfg.setdefault("chatterbox", {}).update(patch["chatterbox"])
        del patch["chatterbox"]
    if "edge" in patch and isinstance(patch["edge"], dict):
        cfg.setdefault("edge", {}).update(patch["edge"])
        del patch["edge"]
    cfg.update(patch)
    _save(cfg)
    return cfg


def get_mood_presets() -> dict:
    return _MOOD_PRESETS


def reference_clip_exists() -> bool:
    return _REFERENCE_CLIP.exists()


def reference_clip_path() -> Path:
    return _REFERENCE_CLIP
