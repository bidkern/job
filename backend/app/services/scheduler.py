from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.automation import run_automation_cycle

scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.local_timezone))


async def _scheduled_run() -> None:
    db: Session = SessionLocal()
    try:
        await run_automation_cycle(db)
    finally:
        db.close()


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        _scheduled_run,
        trigger=CronTrigger(
            hour=settings.automation_hour_local,
            minute=settings.automation_minute_local,
            timezone=ZoneInfo(settings.local_timezone),
        ),
        id="daily_job_scan",
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
