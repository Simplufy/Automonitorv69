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
                ds_params["limit"] = str(items_per_run_limit)
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

def extract_trim_from_title(title: str, year: int, make: str, model: str) -> str | None:
    """Extract trim information from the listing title"""
    if not title or not year or not make or not model:
        return None
    
    # Remove common prefixes
    title = title.replace("Used ", "").replace("Certified ", "").replace("New ", "")
    title = title.replace("Pre-Owned ", "").replace("Certified Pre-Owned ", "")
    
    # Create expected base pattern: "YEAR MAKE MODEL"
    base_pattern = f"{year} {make} {model}"
    
    # Find where the base pattern ends
    base_idx = title.find(base_pattern)
    if base_idx == -1:
        # Try without year
        base_pattern = f"{make} {model}"
        base_idx = title.find(base_pattern)
        
    if base_idx != -1:
        # Extract everything after the base pattern
        remainder = title[base_idx + len(base_pattern):].strip()
        
        # Remove common suffixes that aren't trim
        remainder = remainder.replace(" w/", " with")
        
        # Split and clean up
        parts = [p.strip() for p in remainder.split(" with ") if p.strip()]
        if parts:
            # Join parts that look like trim levels
            trim_parts = []
            for part in parts[0].split():
                # Stop at common non-trim words
                if part.lower() in ["package", "packages", "pkg"]:
                    break
                trim_parts.append(part)
            
            if trim_parts:
                trim = " ".join(trim_parts)
                # Clean up common patterns
                trim = trim.strip("()").strip()
                return trim if len(trim) > 1 else None
    
    return None

def normalize_carscom_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Map raw Cars.com Apify data into our Listing model fields"""
    def g(*keys, default=None):
        for k in keys:
            if k in item and item[k] is not None:
                return item[k]
        return default

    price = g("price", "listingPrice", "currentPrice", "askingPrice")
    if isinstance(price, str):
        try:
            price = int("".join(ch for ch in price if ch.isdigit()))
        except Exception:
            price = None

    # Handle mileage - remove commas if it's a string
    mileage = g("mileage", "odometer", "miles")
    if isinstance(mileage, str):
        try:
            mileage = int("".join(ch for ch in mileage if ch.isdigit()))
        except Exception:
            mileage = None

    # Extract basic info - Cars.com may use different field names
    year = g("year", "modelYear")
    make = g("make", "brand", "manufacturer")
    model = g("model", "modelName")
    
    # Try to get trim from multiple sources
    trim = g("trim", "trimLevel", "package")  # Cars.com specific fields
    
    if not trim:
        # Try extracting from title
        title = g("title", "name", "vehicleName")
        if title and year and make and model:
            trim = extract_trim_from_title(title, year, make, model)
    
    if not trim:
        # Try extracting from specifications or other fields
        specs = g("specifications", "features", {})
        if isinstance(specs, dict):
            # Look for trim-like information in specifications
            for key in ["trim", "package", "level", "edition", "style"]:
                if key in specs and specs[key]:
                    trim = specs[key]
                    break

    return {
        "vin": g("vin", "VIN", "vinNumber"),
        "year": year,
        "make": make,
        "model": model,
        "trim": trim,
        "price": price,
        "mileage": mileage,
        "url": g("url", "detailUrl", "listingUrl", "vehicleUrl"),
        "seller": g("seller", "sellerName", "dealerName", "ownerTitle"),
        "seller_type": g("sellerType", "dealerType"),
        "location": g("location", "cityState", "city_state", "dealerLocation"),
        "lat": g("lat", "latitude"),
        "lon": g("lon", "longitude", "lng"),
        "zip": g("zip", "postalCode", "postal_code", "zipCode"),
        "raw": item,
    }


def normalize_autotrader_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Map raw Autotrader Apify data into our Listing model fields"""
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

    # Extract basic info
    year = g("year")
    make = g("make", "brand")
    model = g("model")
    
    # Try to get trim from multiple sources
    trim = g("trim")  # Direct trim field first
    
    if not trim:
        # Try extracting from title
        title = g("title")
        if title and year and make and model:
            trim = extract_trim_from_title(title, year, make, model)
    
    if not trim:
        # Try extracting from specifications or other fields
        specs = g("specifications", {})
        if isinstance(specs, dict):
            # Look for trim-like information in specifications
            for key in ["trim", "package", "level", "edition"]:
                if key in specs and specs[key]:
                    trim = specs[key]
                    break

    return {
        "vin": g("vin", "VIN"),
        "year": year,
        "make": make,
        "model": model,
        "trim": trim,
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


def normalize_item(item: Dict[str, Any], source: str) -> Dict[str, Any]:
    """Dispatcher to normalize item based on source"""
    if source == "autotrader":
        return normalize_autotrader_item(item)
    elif source == "carscom":
        return normalize_carscom_item(item)
    else:
        # Default to autotrader format for backward compatibility
        return normalize_autotrader_item(item)


async def fetch_and_store_multi_source(
    db: Session,
    runs_to_scan: int = 5,
    items_per_run_limit: int | None = None,
) -> tuple[int, int]:
    """
    Pull latest dataset items from both Autotrader and Cars.com actors,
    upsert Listings by VIN with conflict resolution, score them, and return counts.
    """
    import asyncio
    
    inserted = 0
    skipped = 0
    
    # Get actor IDs with backward compatibility
    autotrader_id = settings.APIFY_AUTOTRADER_ACTOR_ID or settings.APIFY_ACTOR_ID
    carscom_id = settings.APIFY_CARSCOM_ACTOR_ID
    
    if not settings.APIFY_TOKEN:
        return (inserted, skipped)
    
    # Fetch from both sources concurrently
    fetch_tasks = []
    sources = []
    
    if autotrader_id:
        fetch_tasks.append(
            fetch_latest_dataset_items(autotrader_id, runs_to_scan, items_per_run_limit)
        )
        sources.append("autotrader")
        print(f"📊 Fetching from Autotrader actor: {autotrader_id}")
    
    if carscom_id:
        fetch_tasks.append(
            fetch_latest_dataset_items(carscom_id, runs_to_scan, items_per_run_limit)
        )
        sources.append("carscom") 
        print(f"📊 Fetching from Cars.com actor: {carscom_id}")
    
    if not fetch_tasks:
        print("❌ No actor IDs configured")
        return (inserted, skipped)
    
    # Fetch all sources concurrently
    all_items_results = await asyncio.gather(*fetch_tasks)
    
    # Process items from each source
    for source_items, source in zip(all_items_results, sources):
        print(f"🔄 Processing {len(source_items)} items from {source}")
        
        for raw in source_items:
            norm = normalize_item(raw, source)
            vin = norm.get("vin")
            price = norm.get("price")

            if not vin or not price:
                skipped += 1
                continue

            # Handle VIN conflicts - upsert with conflict resolution
            listing = db.query(Listing).filter(Listing.vin == vin).first()
            is_new = listing is None
            
            if is_new:
                listing = Listing(**norm)
                db.add(listing)
                print(f"  ➕ New listing: {vin} from {source}")
            else:
                # Conflict resolution: prefer lower price, minimal mileage, fill missing fields
                old_price = listing.price or float('inf')
                new_price = norm.get("price") or float('inf')
                old_mileage = listing.mileage or float('inf')
                new_mileage = norm.get("mileage") or float('inf')
                
                # Update with better values and fill missing fields
                for k, v in norm.items():
                    if k == "price" and v and (not listing.price or v < listing.price):
                        setattr(listing, k, v)
                    elif k == "mileage" and v and (not listing.mileage or v < listing.mileage):
                        setattr(listing, k, v)
                    elif k == "raw":
                        # Merge raw data sources
                        if not listing.raw:
                            listing.raw = v
                        else:
                            existing_sources = listing.raw.get("sources", [])
                            if source not in existing_sources:
                                existing_sources.append(source)
                            listing.raw["sources"] = existing_sources
                    elif not getattr(listing, k, None) and v:
                        # Fill missing fields
                        setattr(listing, k, v)
                
                listing.ingested_at = datetime.utcnow()
                print(f"  🔄 Updated listing: {vin} from {source} (price: ${old_price} -> ${new_price})")

            db.commit()
            db.refresh(listing)

            # Score the listing
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

    print(f"✅ Multi-source processing complete: {inserted} new, {skipped} skipped")
    return (inserted, skipped)