import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from db import SessionLocal
from verifier import verify_pending_points
from config import settings

log = logging.getLogger("scheduler")
_sched: BackgroundScheduler | None = None


def _verify_job():
    db = SessionLocal()
    try:
        verify_pending_points(db)
    except Exception:
        log.exception("verify_job failed")
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    global _sched
    if _sched is not None:
        return _sched
    _sched = BackgroundScheduler(timezone="Europe/Moscow")
    _sched.add_job(
        _verify_job,
        CronTrigger(
            hour=settings.verify_hour_msk,
            minute=settings.verify_minute_msk,
            day_of_week="mon-fri",
        ),
        id="verify_daily",
        replace_existing=True,
    )
    _sched.start()
    log.info(f"Scheduler started, verify at {settings.verify_hour_msk}:{settings.verify_minute_msk:02d} MSK")
    return _sched


def stop_scheduler():
    global _sched
    if _sched is not None:
        _sched.shutdown(wait=False)
        _sched = None