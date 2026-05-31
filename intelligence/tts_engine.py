"""
TTS Engine — Jarvis voice pipeline.

  synthesize text
      ↓ voice_cloner  (Chatterbox + reference clip, or edge-tts fallback)
      ↓ voice_effects (robotic, warmth, emotion, pitch, tempo)
      ↓ MP3 bytes / Mac speakers

speak(text)              → plays through Mac speakers synchronously
speak_async(text)        → fires and returns, plays in background
speak_to_bytes(text)     → returns MP3 bytes for iOS streaming
speak_to_bytes_async(text) → async version
"""
import asyncio
import subprocess
import tempfile
from pathlib import Path

from observability.logger import log

_FALLBACK_VOICE = "Daniel"   # macOS built-in — used only if everything else fails


def _synthesize_bytes(text: str) -> bytes:
    """Full pipeline: text → cloner → effects → MP3 bytes."""
    if not text or not text.strip():
        return b""
    try:
        from intelligence.voice_config import get_config
        from intelligence.voice_cloner import synthesize
        from intelligence.voice_effects import apply_effects, numpy_to_mp3_bytes

        cfg   = get_config()
        audio, sr = synthesize(text, cfg)
        audio = apply_effects(audio, sr, cfg)
        return numpy_to_mp3_bytes(audio, sr)
    except Exception as e:
        log.warn("tts_pipeline_failed", error=str(e))
        return b""


def _play_mp3_bytes(data: bytes) -> None:
    """Write MP3 to /tmp and play via afplay."""
    if not data:
        return
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        subprocess.run(["afplay", tmp], timeout=120, capture_output=True)
    except Exception:
        pass
    finally:
        Path(tmp).unlink(missing_ok=True)


def speak(text: str) -> None:
    """Speak text through Mac speakers synchronously."""
    if not text or not text.strip():
        return
    data = _synthesize_bytes(text)
    if data:
        _play_mp3_bytes(data)
        log.info("tts_spoke", chars=len(text))
    else:
        try:
            subprocess.run(["say", "-v", _FALLBACK_VOICE, text], timeout=60, capture_output=True)
            log.info("tts_spoke_fallback", chars=len(text))
        except Exception as e:
            log.warn("tts_speak_failed", error=str(e))


async def _play_and_clean_async(path: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "afplay", path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    Path(path).unlink(missing_ok=True)


async def speak_async(text: str) -> None:
    """Non-blocking speak — fires and returns; audio plays in background."""
    if not text or not text.strip():
        return
    data = await asyncio.to_thread(_synthesize_bytes, text)
    if data:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir="/tmp") as f:
            f.write(data)
            tmp = f.name
        asyncio.create_task(_play_and_clean_async(tmp))
        log.info("tts_async_spoke", chars=len(text))
    else:
        await asyncio.create_subprocess_exec(
            "say", "-v", _FALLBACK_VOICE, text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        log.info("tts_async_spoke_fallback", chars=len(text))


def speak_to_bytes(text: str) -> bytes:
    """Generate MP3 bytes — used to stream Jarvis's voice to the iOS app."""
    if not text or not text.strip():
        return b""
    data = _synthesize_bytes(text)
    if data:
        log.info("tts_bytes_generated", chars=len(text), bytes=len(data))
        return data
    # last-resort AIFF from macOS
    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as f:
        out_path = f.name
    try:
        subprocess.run(
            ["say", "-v", _FALLBACK_VOICE, "-o", out_path, text],
            timeout=60, capture_output=True, check=True,
        )
        return Path(out_path).read_bytes()
    except Exception as e:
        log.warn("tts_bytes_fallback_failed", error=str(e))
        return b""
    finally:
        Path(out_path).unlink(missing_ok=True)


async def speak_to_bytes_async(text: str) -> bytes:
    return await asyncio.to_thread(speak_to_bytes, text)
