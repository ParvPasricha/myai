"""
Face Recognition — detect and identify faces in frames.

Uses OpenCV's DNN face detector (no extra models to download — uses YOLO person
class + face crop heuristic on Mac dev) and LBPH recognizer for identity matching.

Architecture is backend-agnostic: swap _extract_embedding() for InsightFace/ArcFace
on Windows GPU without changing any other code.

Known faces stored in:
    vision/known_faces/<name>/  — image files enrolled during calibration
    memory/faces.db             — SQLite: face embeddings + identity map
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

_DB_PATH = Path(__file__).parent.parent / "memory" / "faces.db"
_DB_PATH.parent.mkdir(exist_ok=True)
_KNOWN_FACES_DIR = Path(__file__).parent / "known_faces"
_KNOWN_FACES_DIR.mkdir(exist_ok=True)

# OpenCV face detector (Haar cascade — built into OpenCV, no download)
_CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
_face_cascade: Optional[cv2.CascadeClassifier] = None

# LBPH recognizer for identity matching
_recognizer: Optional[cv2.face.LBPHFaceRecognizer] = None
_label_map: dict[int, str] = {}   # label int → person name
_CONFIDENCE_THRESHOLD = 80        # lower = stricter match (LBPH distance)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _migrate():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS known_faces (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            label       INTEGER NOT NULL UNIQUE,
            enrolled_at REAL NOT NULL,
            image_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS recognition_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   REAL NOT NULL,
            camera_id   TEXT,
            name        TEXT,
            confidence  REAL,
            x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER
        );
        """)


_migrate()


def _get_cascade() -> cv2.CascadeClassifier:
    global _face_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(_CASCADE_PATH)
    return _face_cascade


def _get_recognizer():
    global _recognizer, _label_map
    if _recognizer is not None:
        return _recognizer, _label_map
    _recognizer = cv2.face.LBPHFaceRecognizer_create()
    _label_map = {}
    _rebuild_recognizer()
    return _recognizer, _label_map


def _rebuild_recognizer():
    """Train LBPH recognizer from enrolled face images."""
    global _recognizer, _label_map
    faces, labels = [], []
    with _conn() as c:
        rows = c.execute("SELECT name, label FROM known_faces").fetchall()
        known = {r["name"]: r["label"] for r in rows}

    _label_map = {v: k for k, v in known.items()}

    for name, label in known.items():
        person_dir = _KNOWN_FACES_DIR / name
        if not person_dir.exists():
            continue
        for img_path in person_dir.glob("*.jpg"):
            img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                faces.append(cv2.resize(img, (100, 100)))
                labels.append(label)

    if faces:
        _recognizer = cv2.face.LBPHFaceRecognizer_create()
        _recognizer.train(faces, np.array(labels))


# ── Detection ─────────────────────────────────────────────────────────────────

def detect_faces(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    """
    Detect faces in frame. Returns list of (x1, y1, x2, y2) bounding boxes.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cascade = _get_cascade()
    detections = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
    boxes = []
    for (x, y, w, h) in detections:
        boxes.append((x, y, x + w, y + h))
    return boxes


def identify_face(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int,
                  camera_id: str = "default") -> dict:
    """
    Identify a face crop. Returns {name, confidence, known}.
    """
    recognizer, label_map = _get_recognizer()
    if recognizer is None or not label_map:
        return {"name": "unknown", "confidence": 0.0, "known": False}

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    face_crop = gray[y1:y2, x1:x2]
    if face_crop.size == 0:
        return {"name": "unknown", "confidence": 0.0, "known": False}

    face_resized = cv2.resize(face_crop, (100, 100))
    try:
        label, distance = recognizer.predict(face_resized)
        confidence = max(0, 100 - distance)
        known = distance < _CONFIDENCE_THRESHOLD
        name = label_map.get(label, "unknown") if known else "unknown"
    except Exception:
        name, confidence, known = "unknown", 0.0, False

    # Log recognition
    with _conn() as c:
        c.execute(
            "INSERT INTO recognition_log (timestamp, camera_id, name, confidence, x1, y1, x2, y2) VALUES (?,?,?,?,?,?,?,?)",
            (time.time(), camera_id, name, confidence, x1, y1, x2, y2),
        )

    return {"name": name, "confidence": round(confidence, 1), "known": known}


# ── Enrollment ────────────────────────────────────────────────────────────────

def enroll_face(name: str, frame: np.ndarray) -> dict:
    """
    Enroll a face from a frame. Call multiple times with different angles.
    Returns {"ok": True, "images_stored": N}.
    """
    faces = detect_faces(frame)
    if not faces:
        return {"ok": False, "error": "No face detected in frame"}

    person_dir = _KNOWN_FACES_DIR / name
    person_dir.mkdir(exist_ok=True)

    # Use largest detected face
    x1, y1, x2, y2 = max(faces, key=lambda b: (b[2]-b[0]) * (b[3]-b[1]))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    face_crop = gray[y1:y2, x1:x2]

    img_count = len(list(person_dir.glob("*.jpg")))
    cv2.imwrite(str(person_dir / f"face_{img_count:04d}.jpg"), face_crop)

    # Ensure DB entry
    with _conn() as c:
        existing = c.execute("SELECT label FROM known_faces WHERE name = ?", (name,)).fetchone()
        if not existing:
            max_label = c.execute("SELECT MAX(label) FROM known_faces").fetchone()[0] or 0
            c.execute(
                "INSERT INTO known_faces (name, label, enrolled_at, image_count) VALUES (?,?,?,?)",
                (name, max_label + 1, time.time(), 1),
            )
        else:
            c.execute("UPDATE known_faces SET image_count = image_count + 1 WHERE name = ?", (name,))

    _rebuild_recognizer()
    return {"ok": True, "images_stored": img_count + 1, "name": name}


def list_known_faces() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT name, label, enrolled_at, image_count FROM known_faces").fetchall()
    return [dict(r) for r in rows]


def get_recent_recognitions(limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM recognition_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
