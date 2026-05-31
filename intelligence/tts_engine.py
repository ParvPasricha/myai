"""
TTS Engine — Jarvis voice via macOS Daniel (en_GB).

speak(text)          → plays through Mac speakers immediately (< 100ms latency)
speak_to_bytes(text) → returns AIFF bytes for streaming to iOS

Daniel is a high-quality neural voice built into macOS — no API key needed.
"""
import asyncio
import subprocess
import tempfile
from pathlib import Path

from observability.logger import log

JARVIS_VOICE = "Daniel"   # en_GB British male — closest to Jarvis on macOS


def speak(text: str) -> None:
    """Speak text through Mac speakers synchronously."""
    if not text or not text.strip():
        return
    try:
        subprocess.run(
            ["say", "-v", JARVIS_VOICE, text],
            timeout=60,
            capture_output=True,
        )
        log.info("tts_spoke", chars=len(text))
    except Exception as e:
        log.warn("tts_failed", error=str(e))


async def speak_async(text: str) -> None:
    """Non-blocking speak — returns immediately, audio plays in background."""
    if not text or not text.strip():
        return
    await asyncio.create_subprocess_exec(
        "say", "-v", JARVIS_VOICE, text,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    log.info("tts_async_spoke", chars=len(text))


def speak_to_bytes(text: str) -> bytes:
    """
    Generate AIFF audio bytes for the given text.
    Used to stream Jarvis's voice to the iOS app.
    """
    if not text or not text.strip():
        return b""
    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as f:
        out_path = f.name
    try:
        subprocess.run(
            ["say", "-v", JARVIS_VOICE, "-o", out_path, text],
            timeout=60,
            capture_output=True,
            check=True,
        )
        audio = Path(out_path).read_bytes()
        log.info("tts_bytes_generated", chars=len(text), bytes=len(audio))
        return audio
    except Exception as e:
        log.warn("tts_bytes_failed", error=str(e))
        return b""
    finally:
        Path(out_path).unlink(missing_ok=True)


async def speak_to_bytes_async(text: str) -> bytes:
    return await asyncio.to_thread(speak_to_bytes, text)
