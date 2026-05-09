"""
Behavior Analyzer — detects patterns from emotion timeline + Brain State history.

Runs as part of nightly distillation (called from memory/distill.py).
Also queryable live via GET /vision/behavior.

Patterns detected:
  - Peak focus windows (time of day when focus is highest)
  - Energy dips (time of day when energy consistently drops)
  - Stress triggers (what was happening before stress spikes)
  - Emotion trends (is mood improving week over week?)

Suggestions pushed to iPhone via MQTT (parv/ai/suggestion) when notable.
"""
import json
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

from memory.structured import get_emotion_trend, get_brain_state_history
from observability.logger import log


def analyze_emotion_patterns(hours: int = 72) -> dict:
    """
    Analyze emotion trends over the past N hours.
    Returns patterns + actionable observations.
    """
    emotions = get_emotion_trend(hours=hours)
    if len(emotions) < 3:
        return {"observations": [], "data_points": len(emotions),
                "message": "Not enough data yet — keep the camera running."}

    # Group emotions by hour of day
    by_hour: dict[int, list[str]] = defaultdict(list)
    for e in emotions:
        hour = datetime.fromtimestamp(e["timestamp"]).hour
        by_hour[hour].append(e["emotion"])

    # Find peak focus hours
    focus_hours = []
    for hour, ems in by_hour.items():
        focus_ratio = sum(1 for e in ems if e in ("focused", "neutral")) / len(ems)
        if focus_ratio > 0.6:
            focus_hours.append(hour)

    # Find tired hours
    tired_hours = []
    for hour, ems in by_hour.items():
        tired_ratio = sum(1 for e in ems if e in ("tired", "sad")) / len(ems)
        if tired_ratio > 0.5:
            tired_hours.append(hour)

    # Stress spikes
    stress_times = [
        datetime.fromtimestamp(e["timestamp"]).strftime("%H:%M")
        for e in emotions if e["emotion"] == "angry"
    ]

    # Overall mood score
    positive = sum(1 for e in emotions if e["emotion"] in ("happy", "focused"))
    negative = sum(1 for e in emotions if e["emotion"] in ("angry", "sad", "tired"))
    mood_score = round((positive - negative) / max(len(emotions), 1) * 10, 1)

    observations = []

    if focus_hours:
        hrs = ", ".join(f"{h:02d}:00" for h in sorted(focus_hours)[:3])
        observations.append({
            "type": "peak_focus",
            "message": f"Peak focus detected at {hrs}. Schedule deep work here.",
            "hours": focus_hours,
        })

    if tired_hours:
        hrs = ", ".join(f"{h:02d}:00" for h in sorted(tired_hours)[:3])
        observations.append({
            "type": "energy_dip",
            "message": f"Energy dips consistently at {hrs}. Consider a break or walk.",
            "hours": tired_hours,
        })

    if len(stress_times) > 3:
        observations.append({
            "type": "stress_pattern",
            "message": f"Stress spikes detected {len(stress_times)} times. Review what triggers these.",
            "count": len(stress_times),
        })

    if mood_score < -2:
        observations.append({
            "type": "mood_alert",
            "message": "Consistently negative mood detected this period. Consider a change of activity.",
            "score": mood_score,
        })
    elif mood_score > 3:
        observations.append({
            "type": "mood_positive",
            "message": f"Positive mood trend (score {mood_score}/10). Keep your current routine.",
            "score": mood_score,
        })

    return {
        "observations": observations,
        "data_points": len(emotions),
        "mood_score": mood_score,
        "emotion_distribution": _count_emotions(emotions),
        "hours_analyzed": hours,
    }


def _count_emotions(emotions: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for e in emotions:
        counts[e["emotion"]] += 1
    return dict(counts)


async def generate_daily_suggestions() -> list[str]:
    """
    Generate behavioral suggestions based on today's data.
    Called from nightly distillation.
    """
    patterns = analyze_emotion_patterns(hours=24)
    suggestions = []

    for obs in patterns.get("observations", []):
        suggestions.append(obs["message"])

    # Brain State history check
    history = get_brain_state_history(hours=24)
    if history:
        avg_focus = sum(h["state"].get("focus", 5) for h in history) / len(history)
        avg_stress = sum(h["state"].get("stress", 3) for h in history) / len(history)

        if avg_focus < 4:
            suggestions.append(
                f"Average focus was {avg_focus:.1f}/10 today. Try the Pomodoro technique tomorrow."
            )
        if avg_stress > 7:
            suggestions.append(
                f"High average stress ({avg_stress:.1f}/10) today. Schedule a recovery activity."
            )

    if suggestions:
        try:
            from server.main import mqtt_publish
            for s in suggestions[:3]:
                mqtt_publish("parv/ai/suggestion", s)
        except Exception:
            pass
        log.info("behavior_suggestions_generated", count=len(suggestions))

    return suggestions
