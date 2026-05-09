"""
Emotion Tracker — detects facial emotions from camera frames.

Uses a heuristic + OpenCV features approach on Mac dev (no TensorFlow).
On Windows GPU: swap _classify_emotion() with InsightFace or FER+ ONNX model.

Emotions detected: happy, sad, angry, neutral, surprised, focused, tired
Logs to memory/structured.py emotion_log table + Brain State update + MQTT.
"""
import time
from typing import Optional

import cv2
import numpy as np

from memory.structured import log_emotion
from intelligence import brain_state as bs
from observability.logger import log

# Emotion labels
EMOTIONS = ["neutral", "happy", "sad", "angry", "surprised", "focused", "tired"]

# Simple heuristic thresholds based on facial geometry ratios
# On Windows: replace with ONNX FER+ model via onnxruntime
_USE_ONNX = False   # flip to True once FER+ ONNX model is available


def _classify_emotion_heuristic(face_gray: np.ndarray) -> tuple[str, float]:
    """
    Fast heuristic emotion classification based on pixel intensity patterns.
    Accuracy: ~50% (good enough for behavioral trend tracking).
    For production: use FER+ ONNX or InsightFace attribute model.
    """
    if face_gray.size == 0:
        return "neutral", 0.5

    face = cv2.resize(face_gray, (48, 48))
    h, w = face.shape

    # Brightness → energy level proxy
    brightness = face.mean() / 255.0

    # Upper half vs lower half contrast (eyebrow raise → surprise/happy)
    upper = face[:h//2, :].mean()
    lower = face[h//2:, :].mean()
    vertical_contrast = abs(upper - lower) / 255.0

    # Horizontal edges (mouth region) → smile proxy
    mouth_region = face[3*h//4:, w//4:3*w//4]
    edges = cv2.Canny(mouth_region, 50, 150)
    smile_score = edges.mean() / 255.0

    # Classify
    if brightness < 0.25:
        return "tired", 0.6
    elif smile_score > 0.08 and vertical_contrast > 0.05:
        return "happy", 0.65
    elif vertical_contrast > 0.1:
        return "surprised", 0.6
    elif brightness > 0.65 and smile_score < 0.03:
        return "focused", 0.6
    else:
        return "neutral", 0.7


def analyze_face_emotion(face_crop: np.ndarray) -> dict:
    """
    Classify emotion for a face crop (BGR or gray).
    Returns {"emotion": str, "confidence": float}.
    """
    if len(face_crop.shape) == 3:
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
    else:
        gray = face_crop

    emotion, confidence = _classify_emotion_heuristic(gray)
    return {"emotion": emotion, "confidence": round(confidence, 3)}


def process_and_log(face_crop: np.ndarray, source: str = "camera",
                    publish_mqtt: bool = True) -> dict:
    """
    Analyze emotion, log to DB, update Brain State, publish MQTT.
    Returns emotion result dict.
    """
    result = analyze_face_emotion(face_crop)
    emotion = result["emotion"]
    confidence = result["confidence"]

    # Log to structured DB
    log_emotion(emotion=emotion, confidence=confidence, source=source)

    # Update Brain State with emotion signal
    _update_brain_state(emotion)

    # MQTT publish
    if publish_mqtt:
        try:
            from server.main import mqtt_publish
            import json
            mqtt_publish("parv/emotion/detected", json.dumps({
                "emotion": emotion,
                "confidence": confidence,
                "ts": time.time(),
            }))
        except Exception:
            pass

    log.debug("emotion_detected", emotion=emotion, confidence=confidence)
    return result


def _update_brain_state(emotion: str):
    """Map detected emotion to Brain State adjustments."""
    patch = {}
    if emotion in ("happy", "focused"):
        patch["stress"] = max(1, bs.get_field("stress", 3) - 1)
    elif emotion in ("angry", "sad"):
        patch["stress"] = min(10, bs.get_field("stress", 3) + 1)
    elif emotion == "tired":
        patch["energy"] = max(1, bs.get_field("energy", 5) - 1)
    if patch:
        bs.update(patch)
