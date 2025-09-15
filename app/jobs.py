from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.config import settings
from app.services.apify_client import fetch_latest_dataset_items, normalize_autotrader_item, fetch_and_store_multi_source
from app.db import SessionLocal
from app.models import Listing, MatchResult
from app.services.matching import find_best_appraisal_for_listing
from app.services.scoring import score_listing_async
from datetime import datetime

_scheduler = None

def init_scheduler(app):
    global _scheduler
    if _scheduler:
        return
    _scheduler = AsyncIOScheduler()
    if settings.ENABLE_APIFY_POLLING and (settings.APIFY_AUTOTRADER_ACTOR_ID or settings.APIFY_CARSCOM_ACTOR_ID or settings.APIFY_ACTOR_ID):
        _scheduler.add_job(poll_apify_job, IntervalTrigger(minutes=settings.APIFY_POLL_INTERVAL_MINUTES))
    _scheduler.start()

async def poll_apify_job():
    """Poll both Autotrader and Cars.com actors for new listings"""
    db = SessionLocal()
    try:
        # Use multi-source fetch for both actors
        inserted, skipped = await fetch_and_store_multi_source(db, runs_to_scan=2)
        print(f"📊 Polling complete: {inserted} new listings, {skipped} skipped")
    except Exception as e:
        print(f"❌ Error during polling job: {e}")
    finally:
        db.close()
