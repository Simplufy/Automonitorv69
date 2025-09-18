from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from app.config import settings
from app.services.apify_client import fetch_and_store_multi_source
from app.db import SessionLocal
from app.models import Listing, MatchResult
from app.services.matching import find_best_appraisal_for_listing
from app.services.scoring import score_listing_async
from datetime import datetime
import httpx

_scheduler = None

def init_scheduler(app):
    global _scheduler
    if _scheduler:
        return
    _scheduler = AsyncIOScheduler()
    if settings.ENABLE_APIFY_POLLING and settings.APIFY_CARSCOM_ACTOR_ID:
        _scheduler.add_job(poll_apify_job, IntervalTrigger(minutes=settings.APIFY_POLL_INTERVAL_MINUTES))
    
    # Add Facebook Marketplace daily fetch at 9 AM EST
    _scheduler.add_job(
        poll_facebook_marketplace_job,
        CronTrigger(hour=9, minute=0, timezone="America/New_York"),
        id="facebook_marketplace_daily",
        name="Facebook Marketplace Daily Fetch"
    )
    
    _scheduler.start()
    print("✅ Scheduled daily Facebook Marketplace fetch at 9:00 AM EST")

async def poll_apify_job():
    """Poll Cars.com actor for new listings"""
    db = SessionLocal()
    try:
        # Use multi-source fetch for both actors
        inserted, skipped = await fetch_and_store_multi_source(db, runs_to_scan=2)
        print(f"📊 Polling complete: {inserted} new listings, {skipped} skipped")
    except Exception as e:
        print(f"❌ Error during polling job: {e}")
    finally:
        db.close()

async def poll_facebook_marketplace_job():
    """Fetch Facebook Marketplace listings from BrowseAI completed tasks"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "http://localhost:5000/api/fetch/facebook-marketplace", 
                timeout=300  # 5 minute timeout
            )
            result = response.json()
            
            if result.get("ok"):
                print(f"✅ Daily Facebook Marketplace fetch completed: {result.get('message')}")
                print(f"   - Tasks processed: {result.get('tasks_processed', 0)}")
                print(f"   - Listings processed: {result.get('processed_count', 0)}")
                print(f"   - Failed: {result.get('failed_count', 0)}")
            else:
                print(f"❌ Daily Facebook Marketplace fetch failed: {result.get('message')}")
                
    except Exception as e:
        print(f"❌ Error in Facebook Marketplace fetch: {e}")
