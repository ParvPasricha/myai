"""
Research cron tasks:
    06:00  → generate today's topic + push to iPhone via MQTT
    20:00  → push "Quiz in 2 hours" reminder
    22:00  → generate quiz + push notification
"""
import asyncio
from datetime import datetime

from observability.logger import log


def _seconds_until(hour: int, minute: int = 0) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        # Already past today — schedule for tomorrow
        from datetime import timedelta
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _job_morning_topic():
    log.info("cron_morning_topic_start")
    try:
        from research.topic_generator import generate_today_topic
        topic = await generate_today_topic()
        from server.main import mqtt_publish
        import json
        mqtt_publish("parv/research/topic_assigned", json.dumps({
            "topic": topic["topic"],
            "description": topic["description"],
        }))
        log.info("cron_morning_topic_done", topic=topic["topic"])
    except Exception as e:
        log.error("cron_morning_topic_error", error=str(e))


async def _job_quiz_reminder():
    log.info("cron_quiz_reminder")
    try:
        from server.main import mqtt_publish
        mqtt_publish("parv/research/quiz_reminder", "Quiz time in 2 hours!")
        log.info("cron_quiz_reminder_sent")
    except Exception as e:
        log.error("cron_quiz_reminder_error", error=str(e))


async def _job_quiz_ready():
    log.info("cron_quiz_ready_start")
    try:
        from datetime import date
        from research.db import get_today_topic
        from research.quiz_engine import generate_quiz
        from server.main import mqtt_publish

        today = date.today().isoformat()
        topic = get_today_topic(today)
        if not topic:
            topic_data = await _job_morning_topic()

        topic = get_today_topic(today)
        if topic:
            quiz = await generate_quiz(topic)
            mqtt_publish("parv/research/quiz_ready", str(quiz["quiz_id"]))
            log.info("cron_quiz_ready", quiz_id=quiz["quiz_id"])
    except Exception as e:
        log.error("cron_quiz_ready_error", error=str(e))


async def run_research_scheduler():
    log.info("research_scheduler_started")
    while True:
        now = datetime.now()
        hour = now.hour

        # Calculate next fire time for the earliest upcoming job
        waits = {
            "morning_topic": _seconds_until(6, 0),
            "quiz_reminder":  _seconds_until(20, 0),
            "quiz_ready":     _seconds_until(22, 0),
        }
        next_job = min(waits, key=waits.get)
        wait_secs = waits[next_job]

        log.info("research_scheduler_next", job=next_job,
                 wait_minutes=round(wait_secs / 60))
        await asyncio.sleep(wait_secs)

        if next_job == "morning_topic":
            await _job_morning_topic()
        elif next_job == "quiz_reminder":
            await _job_quiz_reminder()
        elif next_job == "quiz_ready":
            await _job_quiz_ready()

        await asyncio.sleep(60)   # prevent re-firing within same minute
