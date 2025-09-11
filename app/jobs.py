from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.config import settings
from app.services.apify_client import fetch_latest_dataset_items, normalize_autotrader_item
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
    if settings.ENABLE_APIFY_POLLING and settings.APIFY_ACTOR_ID:
        _scheduler.add_job(poll_apify_job, IntervalTrigger(minutes=settings.APIFY_POLL_INTERVAL_MINUTES))
    _scheduler.start()

async def poll_apify_job():
    items = await fetch_latest_dataset_items(settings.APIFY_ACTOR_ID, runs_to_scan=2)
    db = SessionLocal()
    try:
        for raw in items:
            norm = normalize_autotrader_item(raw)
            vin = norm.get("vin")
            price = norm.get("price")
            if not vin or not price:
                continue
            listing = db.query(Listing).filter(Listing.vin==vin).first()
            if listing is None:
                listing = Listing(**norm)
                db.add(listing)
            else:
                for k, v in norm.items():
                    setattr(listing, k, v)
                listing.ingested_at = datetime.utcnow()
            db.commit()
            db.refresh(listing)

            appraisal, level, conf = find_best_appraisal_for_listing(db, listing)
            res = await score_listing_async(listing, appraisal)
            match = db.query(MatchResult).filter(MatchResult.listing_id==listing.id).first()
            if match is None:
                match = MatchResult(listing_id=listing.id, appraisal_id=appraisal.id if appraisal else None,
                                    match_level=level, match_confidence=conf,
                                    shipping_miles=res.get("shipping_miles"),
                                    shipping_cost=res.get("shipping_cost"),
                                    recon_cost=res.get("recon_cost"),
                                    pack_cost=res.get("pack_cost"),
                                    total_cost=res.get("total_cost"),
                                    gross_margin_dollars=res.get("gross_margin_dollars"),
                                    margin_percent=res.get("margin_percent"),
                                    category=res.get("category"),
                                    explanations=res.get("explanations"))
                db.add(match)
            else:
                match.appraisal_id = appraisal.id if appraisal else None
                match.match_level = level
                match.match_confidence = conf
                for k, v in res.items():
                    if k == "explanations":
                        match.explanations = v
                    elif hasattr(match, k):
                        setattr(match, k, v)
                match.scored_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
