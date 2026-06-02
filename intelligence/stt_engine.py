"""
STT Engine — local Whisper transcription via faster-whisper.

Primary:  faster-whisper running locally (base.en model, CPU int8)
Fallback: OpenAI Whisper API when OPENAI_API_KEY is set and local fails

First run downloads ~150 MB model to models/whisper/ automatically.
"""
import asyncio
import tempfile
from functools import lru_cache
from pathlib import Path

from observability.logger import log
from server.config import OPENAI_API_KEY

_WHISPER_MODEL_SIZE = "small.en"  # tiny.en / base.en / small.en / medium.en
_WHISPER_MODEL_DIR  = Path(__file__).parent.parent / "models" / "whisper"


@lru_cache(maxsize=1)
def _get_model():
    """Load faster-whisper model once, cache for the process lifetime."""
    from faster_whisper import WhisperModel
    _WHISPER_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    log.info("stt_loading_model", size=_WHISPER_MODEL_SIZE)
    model = WhisperModel(
        _WHISPER_MODEL_SIZE,
        device="cpu",
        compute_type="int8",
        download_root=str(_WHISPER_MODEL_DIR),
    )
    log.info("stt_model_ready", size=_WHISPER_MODEL_SIZE)
    return model


def transcribe(audio_bytes: bytes, fmt: str = "wav") -> str:
    """Transcribe audio bytes to text. Uses local faster-whisper first."""
    if not audio_bytes:
        return ""

    # ── local faster-whisper ──────────────────────────────────────────────
    try:
        model = _get_model()
        with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as f:
            f.write(audio_bytes)
            audio_path = f.name
        try:
            segments, _info = model.transcribe(
                audio_path,
                language="en",
                beam_size=5,
                best_of=5,
                temperature=0.0,          # greedy — more deterministic
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 300,   # don't cut mid-word
                    "speech_pad_ms": 200,             # keep a little padding around speech
                    "threshold": 0.4,                 # less aggressive VAD
                },
                initial_prompt=(
                    "Jarvis, sir, system, agent, research, plan, email, "
                    "message, memory, project, code, deploy, status"
                ),
            )
            transcript = " ".join(s.text.strip() for s in segments).strip()
            log.info("stt_transcribed_local", chars=len(transcript))
            return transcript
        finally:
            Path(audio_path).unlink(missing_ok=True)
    except Exception as e:
        log.warn("stt_local_failed", error=str(e))

    # ── fallback: OpenAI Whisper API ─────────────────────────────────────
    if not OPENAI_API_KEY:
        log.warn("stt_no_fallback")
        return ""
    try:
        import openai
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as f:
            f.write(audio_bytes)
            audio_path = f.name
        try:
            with open(audio_path, "rb") as af:
                result = client.audio.transcriptions.create(
                    model="whisper-1", file=af, language="en",
                )
            transcript = result.text.strip()
            log.info("stt_transcribed_api", chars=len(transcript))
            return transcript
        finally:
            Path(audio_path).unlink(missing_ok=True)
    except Exception as e:
        log.warn("stt_api_failed", error=str(e))
        return ""


async def transcribe_async(audio_bytes: bytes, fmt: str = "wav") -> str:
    return await asyncio.to_thread(transcribe, audio_bytes, fmt)
