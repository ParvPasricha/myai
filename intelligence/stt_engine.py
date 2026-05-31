"""
STT Engine — Whisper transcription.

transcribe(audio_bytes, fmt="wav") → str

Uses OpenAI Whisper API when OPENAI_API_KEY is set.
Falls back to a clear error so the caller can degrade gracefully.
"""
import asyncio
import tempfile
from pathlib import Path

from observability.logger import log
from server.config import OPENAI_API_KEY


def transcribe(audio_bytes: bytes, fmt: str = "wav") -> str:
    """Transcribe audio bytes to text via Whisper API."""
    if not audio_bytes:
        return ""
    if not OPENAI_API_KEY:
        log.warn("stt_no_key")
        return "[STT unavailable — set OPENAI_API_KEY in .env]"

    import openai
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as f:
        f.write(audio_bytes)
        audio_path = f.name

    try:
        with open(audio_path, "rb") as audio_file:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="en",
            )
        transcript = result.text.strip()
        log.info("stt_transcribed", chars=len(transcript))
        return transcript
    except Exception as e:
        log.warn("stt_failed", error=str(e))
        return ""
    finally:
        Path(audio_path).unlink(missing_ok=True)


async def transcribe_async(audio_bytes: bytes, fmt: str = "wav") -> str:
    return await asyncio.to_thread(transcribe, audio_bytes, fmt)
