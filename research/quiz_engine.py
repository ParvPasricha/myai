"""
Quiz engine — generates questions, evaluates answers, computes scores.

Question format (MCQ):
{
  "id": 1,
  "question": "What is...",
  "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
  "correct": "A",           ← stored server-side only, never sent to client
  "explanation": "..."      ← shown after quiz
}

Scoring:
  Each correct answer = 10 points (10 questions = 100 max)
  Partial credit: not used (MCQ is binary)
  Score stored as float 0-100 for future flexibility
"""
import json
import time
from datetime import date

from research.db import (
    get_today_topic, save_quiz, submit_quiz, get_quiz, get_quiz_for_topic,
)
from server.llm_router import llm
from observability.logger import log


_SYSTEM = """You are a rigorous quiz master for a personal AI learning system.
Generate challenging but fair multiple-choice questions.
Always respond with valid JSON only — no markdown, no explanation outside the JSON."""


async def generate_quiz(topic_row: dict) -> dict:
    """
    Generate a 10-question quiz for the given topic row.
    Returns the quiz dict (questions WITHOUT correct answers — safe to send to client).
    Stores the full quiz (WITH answers) in the database.
    """
    # Check if quiz already exists for today's topic
    existing = get_quiz_for_topic(topic_row["id"])
    if existing:
        return _sanitize_for_client(existing)

    # Generate in two batches of 5 — small models struggle with 10 at once
    questions = []
    for batch_start in (1, 6):
        batch_end = batch_start + 4
        prompt = f"""
Topic: {topic_row["topic"]}
Description: {topic_row["description"]}

Generate exactly 5 multiple-choice questions numbered {batch_start} to {batch_end}.
Mix factual recall and conceptual understanding.

Respond with JSON only:
{{
  "questions": [
    {{
      "id": {batch_start},
      "question": "...",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "correct": "A",
      "explanation": "One sentence why this is correct"
    }}
  ]
}}
"""
        result = await llm.complete(prompt=prompt, system=_SYSTEM, max_tokens=900)
        text = result["text"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
        try:
            batch_data = json.loads(text)
            questions.extend(batch_data["questions"])
        except (json.JSONDecodeError, KeyError) as e:
            log.error("quiz_batch_parse_error", batch_start=batch_start, error=str(e), raw=text[:200])
            raise RuntimeError(f"Quiz generation failed on batch {batch_start}: {e}")

    quiz_id = save_quiz(
        topic_id=topic_row["id"],
        date=topic_row["date"],
        questions=questions,
        ts=time.time(),
    )

    log.info("quiz_generated", topic=topic_row["topic"], questions=len(questions), tier=result["tier"])
    quiz_row = get_quiz(quiz_id)
    return _sanitize_for_client(quiz_row)


async def evaluate_quiz(quiz_id: int, user_answers: list[str]) -> dict:
    """
    Score the submitted answers against stored correct answers.
    user_answers: list of "A"/"B"/"C"/"D" in question order.
    Returns score + breakdown.
    """
    quiz_row = get_quiz(quiz_id)
    if not quiz_row:
        raise ValueError(f"Quiz {quiz_id} not found")
    if quiz_row["completed_at"]:
        raise ValueError("Quiz already submitted")

    questions = json.loads(quiz_row["questions"])
    if len(user_answers) != len(questions):
        raise ValueError(f"Expected {len(questions)} answers, got {len(user_answers)}")

    breakdown = []
    correct_count = 0

    for i, (q, user_ans) in enumerate(zip(questions, user_answers)):
        correct = q["correct"].upper().strip()
        given = (user_ans or "").upper().strip()
        is_correct = given == correct
        if is_correct:
            correct_count += 1
        breakdown.append({
            "id": q["id"],
            "question": q["question"],
            "user_answer": given,
            "correct_answer": correct,
            "correct": is_correct,
            "explanation": q.get("explanation", ""),
        })

    score = round((correct_count / len(questions)) * 100, 1)
    completed_at = time.time()

    submit_quiz(
        quiz_id=quiz_id,
        answers=user_answers,
        score=score,
        breakdown=breakdown,
        completed_at=completed_at,
    )

    log.info("quiz_submitted", quiz_id=quiz_id, score=score,
             correct=correct_count, total=len(questions))

    from research.db import get_streak
    return {
        "quiz_id": quiz_id,
        "score": score,
        "correct": correct_count,
        "total": len(questions),
        "streak": get_streak(),
        "breakdown": breakdown,
        "grade": _grade(score),
    }


def _grade(score: float) -> str:
    if score >= 90: return "S"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 60: return "C"
    if score >= 50: return "D"
    return "F"


def _sanitize_for_client(quiz_row: dict) -> dict:
    """Strip correct answers before sending to the client."""
    questions = json.loads(quiz_row["questions"])
    safe_questions = [
        {k: v for k, v in q.items() if k != "correct" and k != "explanation"}
        for q in questions
    ]
    return {
        "quiz_id": quiz_row["id"],
        "topic_id": quiz_row["topic_id"],
        "date": quiz_row["date"],
        "questions": safe_questions,
        "completed": quiz_row["completed_at"] is not None,
        "score": quiz_row["score"],
    }
