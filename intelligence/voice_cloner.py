"""
Voice cloner — Chatterbox TTS with Jarvis reference clip.

synthesize(text, cfg) → (numpy_float32, sample_rate)

First call downloads ~1 GB Chatterbox model to ~/.cache/huggingface/hub.
Uses the reference clip at models/jarvis_voice/reference.wav when present.
Falls back to edge-tts output if Chatterbox fails or model not loaded.
"""
import asyncio
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Tuple

import numpy as np

from observability.logger import log

AudioResult = Tuple[np.ndarray, int]  # (float32 array, sample_rate)


@lru_cache(maxsize=1)
def _get_chatterbox():
    """Load Chatterbox model once (downloads ~1 GB on first call)."""
    from chatterbox.tts import ChatterboxTTS
    import torch
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    log.info("voice_cloner_loading", device=device)
    model = ChatterboxTTS.from_pretrained(device=device)
    log.info("voice_cloner_ready", device=device)
    return model


def synthesize(text: str, cfg: dict) -> AudioResult:
    """
    Synthesize text using Chatterbox with the Jarvis reference clip.
    Returns (float32 numpy array, sample_rate).
    """
    if not text or not text.strip():
        return np.zeros(1000, dtype=np.float32), 24000

    ref_path = Path(cfg.get("reference_clip", "models/jarvis_voice/reference.wav"))
    cb_cfg   = cfg.get("chatterbox", {})
    exaggeration = float(cb_cfg.get("exaggeration", 0.5))
    cfg_weight   = float(cb_cfg.get("cfg_weight", 0.5))

    try:
        model = _get_chatterbox()
        kwargs = {
            "exaggeration": exaggeration,
            "cfg_weight": cfg_weight,
        }
        if ref_path.exists():
            kwargs["audio_prompt_path"] = str(ref_path)
            log.info("voice_cloner_using_reference", clip=ref_path.name)
        else:
            log.info("voice_cloner_no_reference", hint="drop reference.wav into models/jarvis_voice/")

        wav = model.generate(text, **kwargs)
        # Chatterbox returns a tensor — convert to numpy
        import torch
        if isinstance(wav, torch.Tensor):
            audio = wav.squeeze().cpu().float().numpy()
        else:
            audio = np.array(wav, dtype=np.float32).squeeze()

        sr = 24000  # Chatterbox native sample rate
        log.info("voice_cloner_synthesized", chars=len(text), samples=len(audio), sr=sr)
        return audio, sr

    except Exception as e:
        log.warn("voice_cloner_failed", error=str(e))
        return _edge_fallback(text, cfg)


def _edge_fallback(text: str, cfg: dict) -> AudioResult:
    """Generate audio via edge-tts and return as numpy array."""
    import io, wave
    try:
        import asyncio as _asyncio
        import edge_tts

        edge_cfg = cfg.get("edge", {})
        voice  = edge_cfg.get("voice", "en-GB-RyanNeural")
        rate   = edge_cfg.get("rate", "-5%")
        pitch  = edge_cfg.get("pitch", "-10Hz")

        async def _run() -> bytes:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()
            comm = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
            await comm.save(tmp.name)
            data = Path(tmp.name).read_bytes()
            Path(tmp.name).unlink(missing_ok=True)
            return data

        try:
            loop = _asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                mp3_bytes = ex.submit(_asyncio.run, _run()).result(timeout=30)
        except RuntimeError:
            mp3_bytes = _asyncio.run(_run())

        # decode MP3 → numpy via pydub
        from pydub import AudioSegment
        seg = AudioSegment.from_mp3(io.BytesIO(mp3_bytes)).set_channels(1).set_frame_rate(24000)
        samples = np.array(seg.get_array_of_samples(), dtype=np.int16).astype(np.float32) / 32768.0
        return samples, 24000
    except Exception as e:
        log.warn("voice_cloner_edge_fallback_failed", error=str(e))
        return np.zeros(1000, dtype=np.float32), 24000


async def synthesize_async(text: str, cfg: dict) -> AudioResult:
    return await asyncio.to_thread(synthesize, text, cfg)
