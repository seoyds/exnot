"""Celery Beat schedule definitions for ExNot periodic tasks."""

from celery.schedules import crontab

from exnot.workers.celery_app import celery_app

celery_app.conf.beat_schedule = {
    "daily_fee_check": {
        "task": "exnot.workers.tasks.daily_fee_schedule_check",
        "schedule": crontab(hour=6, minute=0),  # 6:00 AM ET daily
        "options": {"queue": "default"},
    },
    "daily_digest": {
        "task": "exnot.workers.tasks.send_daily_digest",
        "schedule": crontab(hour=7, minute=0),  # 7:00 AM ET daily
        "options": {"queue": "notifications"},
    },
    "weekly_summary": {
        "task": "exnot.workers.tasks.send_weekly_summary",
        "schedule": crontab(hour=8, minute=0, day_of_week="monday"),  # Monday 8:00 AM ET
        "options": {"queue": "notifications"},
    },
    "cleanup_logs": {
        "task": "exnot.workers.tasks.cleanup_old_scrape_logs",
        "schedule": crontab(hour=2, minute=0, day_of_week="sunday"),  # Sunday 2:00 AM ET
        "options": {"queue": "default"},
    },
}
