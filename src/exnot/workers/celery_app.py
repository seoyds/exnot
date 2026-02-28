"""Celery application configuration for ExNot worker infrastructure."""

from celery import Celery
from kombu import Exchange, Queue

from exnot.config import get_settings

settings = get_settings()

celery_app = Celery("exnot")

# Broker and result backend
celery_app.conf.broker_url = settings.redis_url
celery_app.conf.result_backend = settings.redis_url

# Serialization
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]

# Timezone
celery_app.conf.timezone = "US/Eastern"
celery_app.conf.enable_utc = True

# Task queues
default_exchange = Exchange("default", type="direct")
celery_app.conf.task_queues = (
    Queue("default", default_exchange, routing_key="default"),
    Queue("scraping", Exchange("scraping", type="direct"), routing_key="scraping"),
    Queue("parsing", Exchange("parsing", type="direct"), routing_key="parsing"),
    Queue("notifications", Exchange("notifications", type="direct"), routing_key="notifications"),
)
celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "default"

# Task routing
celery_app.conf.task_routes = {
    "exnot.workers.tasks.daily_fee_schedule_check": {"queue": "default"},
    "exnot.workers.tasks.scrape_and_process_exchange": {"queue": "scraping"},
    "exnot.workers.tasks.send_change_notifications": {"queue": "notifications"},
    "exnot.workers.tasks.send_daily_digest": {"queue": "notifications"},
    "exnot.workers.tasks.send_weekly_summary": {"queue": "notifications"},
    "exnot.workers.tasks.cleanup_old_scrape_logs": {"queue": "default"},
}

# Task execution settings
celery_app.conf.task_acks_late = True
celery_app.conf.worker_prefetch_multiplier = 1
celery_app.conf.task_track_started = True
celery_app.conf.task_time_limit = 1800  # 30 minutes hard limit (sectioned extraction may need 4+ AI calls)
celery_app.conf.task_soft_time_limit = 1500  # 25 minutes soft limit

# Result settings
celery_app.conf.result_expires = 86400  # 24 hours

# Auto-discover tasks
celery_app.autodiscover_tasks(["exnot.workers.tasks"])
