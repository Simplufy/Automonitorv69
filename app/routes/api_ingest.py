from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.db import SessionLocal
from app.schemas import ListingIn
from app.models import Listing, MatchResult
from app.services.matching import find_best_appraisal_for_listing
from app.services.scoring import score_listing
from app.services.llm_parser import VehicleParser
from app.services.market_pricing import price_listing_with_market
import os

router = APIRouter(prefix="/api")

@router.post("/ingest")
def ingest_listing(payload: ListingIn):
    db: Session = SessionLocal()
    try:
        listing = db.query(Listing).filter(Listing.vin==payload.vin).first()
        if listing is None:
            listing = Listing(**payload.dict())
            db.add(listing)
        else:
            for k, v in payload.dict().items():
                setattr(listing, k, v)
            listing.ingested_at = datetime.utcnow()
        db.commit()
        db.refresh(listing)

        appraisal, level, conf = find_best_appraisal_for_listing(db, listing)
        res = score_listing(listing, appraisal)
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
        
        # --- Market pricing add-on (OpenAI-assisted comps) ---
        try:
            market = price_listing_with_market(db, listing)
            if market:
                ex = match.explanations or {}
                ex["market_pricing"] = market

                # Profit logic (user-defined):
                # margin_dollars = list_price - predicted_price (negative means under market)
                # margin_pct     = (list_price - predicted_price) / predicted_price
                required_margin = float(os.environ.get("DESIRED_MARGIN","700"))
                required_pct    = float(os.environ.get("REQUIRED_MARGIN_PCT","0.03"))  # 3%

                if market.get("predicted_price") is not None and listing.price is not None:
                    list_price = float(listing.price)
                    predicted  = float(market["predicted_price"])
                    margin_dollars = list_price - predicted
                    margin_pct = (list_price - predicted) / predicted if predicted else 0.0

                    ex["market_pricing"]["margin_dollars"] = margin_dollars
                    ex["market_pricing"]["margin_pct"] = margin_pct

                    # We want listings priced BELOW predicted by at least $ and %
                    if (margin_dollars <= -required_margin) and (margin_pct <= -required_pct):
                        match.category = match.category or "BUY"

                match.explanations = ex
        except Exception as e:
            ex = match.explanations or {}
            ex["market_pricing_error"] = str(e)
            match.explanations = ex
        # -----------------------------------------------------
    

        db.commit()
        db.refresh(match)
        return {"ok": True, "listing_id": listing.id, "match_id": match.id}
    finally:
        db.close()


@router.post("/ingest-freeform")
def ingest_freeform(payload: dict):
    """Accepts {title, price, mileage, url, vin?, seller?, location?, ...}
    Parses Y/M/M/T with OpenAI, then forwards into the standard ingest flow.
    """
    db: Session = SessionLocal()
    try:
        parser = VehicleParser()
        title = str(payload.get("title",""))
        parsed = parser.parse(title)
        if not parsed.get("make") or not parsed.get("model") or not parsed.get("year"):
            return {"ok": False, "error": "parser_low_confidence", "parsed": parsed}
        data = {
            "vin": payload.get("vin") or title[:17],
            "year": int(parsed["year"]),
            "make": parsed["make"],
            "model": parsed["model"],
            "trim": parsed.get("trim"),
            "price": int(payload.get("price") or 0),
            "mileage": int(payload.get("mileage") or 0),
            "url": payload.get("url") or "N/A",
            "seller": payload.get("seller"),
            "seller_type": payload.get("seller_type"),
            "location": payload.get("location"),
            "lat": payload.get("lat"),
            "lon": payload.get("lon"),
            "zip": payload.get("zip"),
            "source": payload.get("source") or "apify_generic",
            "raw": payload
        }
        # Reuse existing logic by calling ingest_listing directly
        return ingest_listing(ListingIn(**data))
    finally:
        db.close()


def normalize_facebook_marketplace_item(item: dict) -> dict:
    """Normalize Facebook Marketplace scraped data to ListingIn format"""
    import hashlib
    import re
    
    def g(*keys, default=None):
        for k in keys:
            if k in item and item[k] is not None:
                return item[k]
        return default

    # Handle price - Facebook format: "$32,300" or "$32,000\n$34,000"
    price_str = g("Price", "price", default="0")
    if isinstance(price_str, str):
        # Handle multiple prices (take the first one)
        price_str = price_str.split('\n')[0]
        # Remove $ and commas, extract digits
        price = int("".join(ch for ch in price_str if ch.isdigit()) or 0)
    else:
        price = 0

    # Handle mileage - Facebook format: "56K miles" or "56K miles · Dealership"
    mileage_str = g("Mileage", "mileage", default="")
    mileage = None
    if isinstance(mileage_str, str):
        # Extract number and K multiplier
        match = re.search(r'(\d+)K?\s*miles', mileage_str, re.IGNORECASE)
        if match:
            mileage_num = int(match.group(1))
            if 'K' in mileage_str.upper():
                mileage = mileage_num * 1000
            else:
                mileage = mileage_num

    # Parse Car Model - Facebook format: "2020 BMW x5 xDrive40i Sport Utility 4D"
    car_model = g("Car Model", "title", "name", default="")
    year = None
    make = None
    model = None
    trim = None
    
    if car_model:
        # Extract year (4 digits at start)
        year_match = re.search(r'^(\d{4})\s+', car_model)
        if year_match:
            year = int(year_match.group(1))
            # Remove year from string for further parsing
            remaining = car_model[year_match.end():].strip()
            
            # Split remaining into parts
            parts = remaining.split()
            if len(parts) >= 2:
                make = parts[0]  # BMW
                model = parts[1]  # x5
                
                # Everything after make/model is trim
                if len(parts) > 2:
                    trim_parts = parts[2:]
                    # Filter out common suffixes
                    trim_parts = [p for p in trim_parts if p.lower() not in ['sport', 'utility', '4d']]
                    trim = ' '.join(trim_parts) if trim_parts else None

    # Generate VIN from listing URL for deduplication
    listing_url = g("Listing URL", "url", "link", default="")
    vin = None
    if listing_url:
        # Extract Facebook item ID from URL for deterministic VIN
        match = re.search(r'/item/(\d+)/?', listing_url)
        if match:
            fb_id = match.group(1)
            # Create deterministic VIN from Facebook item ID
            vin_data = f"FB_{fb_id}_{car_model}".encode('utf-8')
            vin_hash = hashlib.sha256(vin_data).hexdigest()[:13]
            vin = f"FB{vin_hash}00"[:17]
    
    if not vin:
        # Fallback VIN generation
        vin_data = f"FB_{car_model}_{price}".encode('utf-8')
        vin_hash = hashlib.sha256(vin_data).hexdigest()[:13]
        vin = f"FB{vin_hash}00"[:17]

    # Handle images - Facebook uses single "Car Image" field
    raw_item = item.copy()
    car_image = g("Car Image", "image", "photo", default=None)
    if car_image:
        raw_item["images"] = [car_image]

    # Determine seller type from mileage field
    seller_type = "dealership" if "dealership" in mileage_str.lower() else "private"

    return {
        "vin": vin,
        "year": year or 0,
        "make": make,
        "model": model, 
        "trim": trim,
        "price": price,
        "mileage": mileage,
        "url": listing_url or "https://facebook.com/marketplace",
        "seller": None,  # Not provided in this format
        "seller_type": seller_type,
        "location": g("Location", "location", default=None),
        "lat": None,  # Not provided in this format
        "lon": None,  # Not provided in this format
        "zip": None,  # Not provided in this format
        "source": "facebook_marketplace",
        "raw": raw_item,
    }


@router.post("/fetch/facebook-marketplace")  
def fetch_facebook_marketplace_listings(request: dict = None):
    """
    Fetch Facebook Marketplace listings using BrowseAI REST API
    
    Request format (optional):
    {
        "originUrl": "https://www.facebook.com/marketplace/category/vehicles", 
        "cars_for_sale_limit": 50
    }
    """
    import httpx
    import os
    
    try:
        # BrowseAI API configuration from the provided image
        workspace_id = "10d44422-affe-4988-8864-bfdd2186bc7f"
        robot_id = "b7b01349-ff3d-4853-b1e7-92e391cadc08"
        
        # Get API key from environment variables
        api_key = os.getenv("BROWSEAI_API_KEY")
        if not api_key:
            return {"ok": False, "error": "missing_api_key", "message": "BrowseAI API key not found"}
        
        # Set default parameters or use provided ones
        if request is None:
            request = {}
            
        origin_url = request.get("originUrl", "https://www.facebook.com/marketplace/category/vehicles")
        limit = request.get("cars_for_sale_limit", 50)
        
        # Call BrowseAI REST API to trigger robot
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        robot_data = {
            "originUrl": origin_url,
            "cars_for_sale_limit": limit
        }
        
        with httpx.Client() as client:
            # Trigger the robot
            response = client.post(
                f"https://api.browse.ai/v2/robots/{robot_id}/tasks",
                headers=headers,
                json=robot_data,
                timeout=30
            )
            
            if response.status_code not in [200, 201]:
                return {
                    "ok": False, 
                    "error": "browseai_error",
                    "message": f"BrowseAI API error: {response.text}"
                }
            
            task_data = response.json()
            task_id = task_data.get("result", {}).get("id")
            
            if not task_id:
                return {"ok": False, "error": "no_task_id", "message": "Failed to get task ID from BrowseAI"}
            
            # Wait for task completion and get results
            import time
            max_wait = 300  # 5 minutes max wait
            wait_time = 0
            
            while wait_time < max_wait:
                time.sleep(10)  # Wait 10 seconds between checks
                wait_time += 10
                
                # Check task status
                status_response = client.get(
                    f"https://api.browse.ai/v2/robots/{robot_id}/tasks/{task_id}",
                    headers=headers,
                    timeout=30
                )
                
                if status_response.status_code == 200:
                    task_status = status_response.json()
                    status = task_status.get("result", {}).get("status")
                    
                    if status == "successful":
                        # Get the captured data
                        captured_lists = task_status.get("result", {}).get("capturedLists", {})
                        
                        # Process the listings
                        processed_count = 0
                        failed_count = 0
                        
                        # Process each captured list (likely just one for cars)
                        for list_name, listings in captured_lists.items():
                            for listing in listings:
                                try:
                                    # Normalize the BrowseAI data to our format
                                    normalized = normalize_facebook_marketplace_item(listing)
                                    
                                    # Validate required fields
                                    make = normalized.get("make")
                                    model = normalized.get("model")
                                    year = normalized.get("year", 0)
                                    price = normalized.get("price", 0)
                                    
                                    if (make and model and year >= 1900 and year <= 2030 and 
                                        price > 0 and make.lower() not in ["unknown", "n/a", "none", ""] and 
                                        model.lower() not in ["unknown", "n/a", "none", ""]):
                                        
                                        # Process the listing
                                        listing_data = ListingIn(**normalized)
                                        result = ingest_listing(listing_data)
                                        processed_count += 1
                                    else:
                                        failed_count += 1
                                        
                                except Exception as e:
                                    failed_count += 1
                                    continue
                        
                        return {
                            "ok": True,
                            "message": "Facebook Marketplace listings fetched and processed successfully",
                            "task_id": task_id,
                            "processed_count": processed_count,
                            "failed_count": failed_count,
                            "total_listings": processed_count + failed_count
                        }
                    
                    elif status == "failed":
                        return {
                            "ok": False,
                            "error": "browseai_task_failed", 
                            "message": f"BrowseAI task failed: {task_status.get('result', {}).get('error', 'Unknown error')}"
                        }
                    
                    # Task still running, continue waiting
                
            # Timeout reached
            return {
                "ok": False,
                "error": "timeout", 
                "message": f"Task {task_id} did not complete within {max_wait} seconds"
            }
        
    except Exception as e:
        return {"ok": False, "error": "processing_error", "message": str(e)}
