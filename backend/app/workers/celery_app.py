from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "sentinellai",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.evidence_tasks",
        "app.workers.evaluation_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "collect-evidence-every-5-min": {
        "task": "app.workers.evidence_tasks.scheduled_evidence_collection",
        "schedule": crontab(minute="*/5"),
    },
    "evaluate-controls-every-5-min": {
        "task": "app.workers.evaluation_tasks.scheduled_evaluation",
        "schedule": crontab(minute="*/5"),
    },
}
