from typing import List, Dict, Any, Optional
import httpx
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Listing, MatchResult
from app.services.matching import find_best_appraisal_for_listing
from app.services.scoring import score_listing_async

APIFY_BASE = "https://api.apify.com/v2"

async def fetch_latest_dataset_items(
    actor_id: str, runs_to_scan: int = 5, items_per_run_limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Fetch dataset items from Apify actor runs"""
    if not settings.APIFY_TOKEN or not actor_id:
        print(f"Missing APIFY_TOKEN or actor_id. Token: {'***' if settings.APIFY_TOKEN else 'None'}, Actor: {actor_id}")
        return []

    params = {"token": settings.APIFY_TOKEN}
    items: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            runs_url = f"{APIFY_BASE}/acts/{actor_id}/runs"
            print(f"Fetching from URL: {runs_url}")
            runs_resp = await client.get(runs_url, params=params)
            runs_resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            print(f"HTTP Error {e.response.status_code}: {e.response.text}")
            print(f"URL: {e.request.url}")
            raise

        runs_data = runs_resp.json().get("data", {}).get("items", [])
        print(f"Found {len(runs_data)} total runs, scanning latest {runs_to_scan}")
        runs = runs_data[:runs_to_scan]

        for i, run in enumerate(runs):
            dataset_id = run.get("defaultDatasetId")
            run_status = run.get("status")
            run_started = run.get("startedAt")
            print(f"Run {i+1}: Status={run_status}, Started={run_started}, DatasetID={dataset_id}")

            if not dataset_id:
                print(f"  Skipping run {i+1} - no dataset ID")
                continue

            ds_params = {"token": settings.APIFY_TOKEN}
            # Remove any default limits to get ALL items from each run
            if items_per_run_limit:
                ds_params["limit"] = items_per_run_limit
                print(f"  Fetching max {items_per_run_limit} items from dataset {dataset_id}")
            else:
                print(f"  Fetching ALL items from dataset {dataset_id}")

            ds_resp = await client.get(f"{APIFY_BASE}/datasets/{dataset_id}/items", params=ds_params)
            ds_resp.raise_for_status()
            run_items = ds_resp.json()
            print(f"  Retrieved {len(run_items)} items from run {i+1}")
            items.extend(run_items)

    print(f"Total items collected: {len(items)}")
    return items

def normalize_autotrader_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Map raw Apify data into our Listing model fields"""
    def g(*keys, default=None):
        for k in keys:
            if k in item and item[k] is not None:
                return item[k]
        return default

    price = g("price", "listingPrice", "currentPrice")
    if isinstance(price, str):
        try:
            price = int("".join(ch for ch in price if ch.isdigit()))
        except Exception:
            price = None

    # Handle mileage - remove commas if it's a string
    mileage = g("mileage", "odometer")
    if isinstance(mileage, str):
        try:
            mileage = int("".join(ch for ch in mileage if ch.isdigit()))
        except Exception:
            mileage = None

    return {
        "vin": g("vin", "VIN"),
        "year": g("year"),
        "make": g("make", "brand"),  # Map brand to make
        "model": g("model"),
        "trim": g("trim"),
        "price": price,
        "mileage": mileage,
        "url": g("url", "detailUrl", "listingUrl"),
        "seller": g("seller", "sellerName", "ownerTitle"),
        "seller_type": g("sellerType"),
        "location": g("location", "cityState", "city_state"),
        "lat": g("lat", "latitude"),
        "lon": g("lon", "longitude", "lng"),
        "zip": g("zip", "postalCode", "postal_code"),
        "raw": item,
    }

async def fetch_and_store_latest(
    db: Session,
    runs_to_scan: int = 5,
    items_per_run_limit: int | None = None,
) -> tuple[int, int]:
    """
    Pull latest dataset items from Apify, upsert Listings by VIN,
    score them against the appraisal DB, and return (inserted_count, skipped_count).
    """
    inserted = 0
    skipped = 0

    if not settings.APIFY_ACTOR_ID or not settings.APIFY_TOKEN:
        return (inserted, skipped)

    items = await fetch_latest_dataset_items(
        settings.APIFY_ACTOR_ID,
        runs_to_scan=runs_to_scan,
        items_per_run_limit=items_per_run_limit,
    )

    for raw in items:
        norm = normalize_autotrader_item(raw)
        vin = norm.get("vin")
        price = norm.get("price")

        if not vin or not price:
            skipped += 1
            continue

        listing = db.query(Listing).filter(Listing.vin == vin).first()
        is_new = listing is None
        if is_new:
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

        match = db.query(MatchResult).filter(MatchResult.listing_id == listing.id).first()
        if match is None:
            match = MatchResult(
                listing_id=listing.id,
                appraisal_id=appraisal.id if appraisal else None,
                match_level=level,
                match_confidence=conf,
                shipping_miles=res.get("shipping_miles"),
                shipping_cost=res.get("shipping_cost"),
                recon_cost=res.get("recon_cost"),
                pack_cost=res.get("pack_cost"),
                total_cost=res.get("total_cost"),
                gross_margin_dollars=res.get("gross_margin_dollars"),
                margin_percent=res.get("margin_percent"),
                category=res.get("category"),
                explanations=res.get("explanations"),
                scored_at=datetime.utcnow(),
            )
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
        if is_new:
            inserted += 1

    return (inserted, skipped)