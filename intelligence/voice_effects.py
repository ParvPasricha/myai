"""
Voice effects pipeline — applied after synthesis.

All functions take/return numpy float32 arrays + sample_rate.
Call apply_effects(audio_np, sr, cfg) for the full chain.
"""
import numpy as np
from typing import Tuple

from observability.logger import log

AudioNP = np.ndarray  # float32, shape (N,) or (N, channels)


# ── Individual effects ────────────────────────────────────────────────────────

def ring_modulate(audio: AudioNP, sr: int, depth: float) -> AudioNP:
    """
    Robotic ring modulator — carrier at 150 Hz creates the metallic buzz.
    depth 0.0=off, 1.0=full effect.
    """
    if depth < 0.01:
        return audio
    carrier_freq = 150.0
    t = np.arange(len(audio), dtype=np.float32) / sr
    carrier = np.sin(2 * np.pi * carrier_freq * t).astype(np.float32)
    modulated = audio * carrier
    return ((1 - depth) * audio + depth * modulated).astype(np.float32)


def add_warmth(audio: AudioNP, sr: int, level: float) -> AudioNP:
    """
    Warmth via gentle low-shelf boost + subtle reverb simulation (comb filter).
    level 0.0=off, 1.0=max warmth.
    """
    if level < 0.01:
        return audio
    try:
        from pedalboard import Pedalboard, Reverb, LowShelfFilter
        board = Pedalboard([
            LowShelfFilter(cutoff_frequency_hz=300, gain_db=level * 4.0, q=0.7),
            Reverb(room_size=level * 0.15, damping=0.7, wet_level=level * 0.08, dry_level=1.0),
        ])
        return board(audio.reshape(1, -1), sr).flatten()
    except Exception as e:
        log.warn("voice_warmth_failed", error=str(e))
        return audio


def adjust_dynamics(audio: AudioNP, sr: int, emotion_intensity: float) -> AudioNP:
    """
    emotion_intensity 0=heavily compressed (robotic/flat) → 100=wide dynamic range (expressive).
    Uses pedalboard Compressor: high ratio = flat, low ratio = natural.
    """
    try:
        from pedalboard import Pedalboard, Compressor
        # map 0→100 to ratio 20:1→1.5:1
        ratio = 20.0 - (emotion_intensity / 100.0) * 18.5
        threshold = -20.0 + (emotion_intensity / 100.0) * 10.0  # -20 to -10 dB
        board = Pedalboard([
            Compressor(threshold_db=threshold, ratio=ratio, attack_ms=5, release_ms=100)
        ])
        return board(audio.reshape(1, -1), sr).flatten()
    except Exception as e:
        log.warn("voice_dynamics_failed", error=str(e))
        return audio


def pitch_shift_audio(audio: AudioNP, sr: int, semitones: float) -> AudioNP:
    """Shift pitch by ±semitones using librosa."""
    if abs(semitones) < 0.05:
        return audio
    try:
        import librosa
        return librosa.effects.pitch_shift(audio, sr=sr, n_steps=semitones)
    except Exception as e:
        log.warn("voice_pitch_shift_failed", error=str(e))
        return audio


def time_stretch_audio(audio: AudioNP, sr: int, rate: float) -> AudioNP:
    """Stretch/compress tempo by rate (1.0=unchanged, 0.9=10% slower)."""
    if abs(rate - 1.0) < 0.01:
        return audio
    try:
        import librosa
        return librosa.effects.time_stretch(audio, rate=rate)
    except Exception as e:
        log.warn("voice_tempo_failed", error=str(e))
        return audio


# ── Full chain ────────────────────────────────────────────────────────────────

def apply_effects(audio: AudioNP, sr: int, cfg: dict) -> AudioNP:
    """
    Apply the full effects chain from config.
    Order: dynamics → pitch → tempo → robotic → warmth → normalize
    """
    fx = cfg.get("effects", {})
    audio = audio.astype(np.float32)

    robotic   = fx.get("robotic", 0) / 100.0
    warmth    = fx.get("warmth", 25) / 100.0
    emotion   = fx.get("emotion_intensity", 50)
    pitch     = fx.get("pitch_shift", 0)
    tempo     = fx.get("tempo", 1.0)

    audio = adjust_dynamics(audio, sr, emotion)
    audio = pitch_shift_audio(audio, sr, pitch)
    audio = time_stretch_audio(audio, sr, tempo)
    audio = ring_modulate(audio, sr, robotic)
    audio = add_warmth(audio, sr, warmth)

    # normalize to -1..+1, prevent clipping
    peak = np.abs(audio).max()
    if peak > 0.01:
        audio = audio / peak * 0.9

    return audio.astype(np.float32)


# ── Audio format helpers ──────────────────────────────────────────────────────

def numpy_to_mp3_bytes(audio: AudioNP, sr: int) -> bytes:
    """Convert float32 numpy array → MP3 bytes via pydub."""
    import io
    import struct
    try:
        from pydub import AudioSegment
        pcm = (audio * 32767).astype(np.int16).tobytes()
        seg = AudioSegment(pcm, frame_rate=sr, sample_width=2, channels=1)
        buf = io.BytesIO()
        seg.export(buf, format="mp3", bitrate="128k")
        return buf.getvalue()
    except Exception as e:
        log.warn("numpy_to_mp3_failed", error=str(e))
        return numpy_to_wav_bytes(audio, sr)


def numpy_to_wav_bytes(audio: AudioNP, sr: int) -> bytes:
    """Convert float32 numpy array → WAV bytes (fallback)."""
    import io, wave
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm)
    return buf.getvalue()
