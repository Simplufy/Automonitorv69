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
    """Normalize Facebook Marketplace webhook data to ListingIn format"""
    import hashlib
    
    def g(*keys, default=None):
        for k in keys:
            if k in item and item[k] is not None:
                return item[k]
        return default

    # Handle price - ensure it's an integer
    price = g("price", "asking_price", "cost", default=0)
    if isinstance(price, str):
        try:
            price = int("".join(ch for ch in price if ch.isdigit()))
        except Exception:
            price = 0

    # Handle mileage 
    mileage = g("mileage", "odometer", "miles", default=None)
    if isinstance(mileage, str):
        try:
            mileage = int("".join(ch for ch in mileage if ch.isdigit()))
        except Exception:
            mileage = None

    # Generate VIN if not provided (Facebook often doesn't have VIN)
    vin = g("vin", "VIN", default=None)
    if not vin:
        # Create a deterministic pseudo-VIN from item data for deduplication
        title = g("title", "name", "description", default="")
        fb_id = g("id", "listing_id", "post_id", default="")
        # Use deterministic hash for consistent VIN generation
        vin_data = f"FB_{fb_id}_{title}".encode('utf-8')
        vin_hash = hashlib.sha256(vin_data).hexdigest()[:13]  # 13 chars + "FB" prefix = 15, pad to 17
        vin = f"FB{vin_hash}00"[:17]

    # Handle images - Facebook uses different field names
    raw_item = item.copy()
    images = g("images", "photos", "picture", "image_urls", default=None)
    if images:
        if isinstance(images, str):
            # Single image URL
            raw_item["images"] = [images]
        elif isinstance(images, list):
            # List of image URLs
            raw_item["images"] = images

    return {
        "vin": vin,
        "year": int(g("year", "model_year", default=0) or 0),
        "make": g("make", "brand", "manufacturer", default=None),
        "model": g("model", "model_name", default=None),
        "trim": g("trim", "variant", "trim_level", default=None),
        "price": price,
        "mileage": mileage,
        "url": g("url", "link", "facebook_url", default="https://facebook.com/marketplace"),
        "seller": g("seller", "seller_name", "posted_by", default=None),
        "seller_type": "private",  # Facebook Marketplace is typically private sellers
        "location": g("location", "city", "address", default=None),
        "lat": g("lat", "latitude", default=None),
        "lon": g("lon", "longitude", "lng", default=None),
        "zip": g("zip", "postal_code", "zipcode", default=None),
        "source": "facebook_marketplace",
        "raw": raw_item,
    }


@router.post("/webhook/facebook-marketplace")
def webhook_facebook_marketplace(payload: dict):
    """
    Facebook Marketplace webhook endpoint
    Accepts vehicle listings from Facebook Marketplace and processes them through AutoProfit
    
    Expected payload format:
    {
        "title": "2020 Honda Civic LX",
        "price": 18000,
        "mileage": 45000,
        "year": 2020,
        "make": "Honda", 
        "model": "Civic",
        "trim": "LX",
        "location": "San Francisco, CA",
        "images": ["https://...", "https://..."],
        "url": "https://facebook.com/marketplace/item/...",
        "seller": "John Doe"
    }
    """
    try:
        # If the payload contains vehicle info, parse it with OpenAI
        title = payload.get("title", "")
        if title and not all([payload.get("year"), payload.get("make"), payload.get("model")]):
            parser = VehicleParser()
            parsed = parser.parse(title)
            
            # Update payload with parsed vehicle info if missing
            if not payload.get("year") and parsed.get("year"):
                payload["year"] = parsed["year"]
            if not payload.get("make") and parsed.get("make"):
                payload["make"] = parsed["make"] 
            if not payload.get("model") and parsed.get("model"):
                payload["model"] = parsed["model"]
            if not payload.get("trim") and parsed.get("trim"):
                payload["trim"] = parsed["trim"]

        # Normalize Facebook data to our format
        normalized = normalize_facebook_marketplace_item(payload)
        
        # Ensure required fields are present and valid
        make = normalized.get("make")
        model = normalized.get("model") 
        year = normalized.get("year", 0)
        
        if not make or not model or not year:
            return {"ok": False, "error": "missing_vehicle_info", "message": "Year, make, and model are required"}
        
        # Reject placeholder values 
        if make.lower() in ["unknown", "n/a", "none", ""] or model.lower() in ["unknown", "n/a", "none", ""]:
            return {"ok": False, "error": "invalid_vehicle_info", "message": "Valid make and model are required (no placeholders)"}
            
        if year < 1900 or year > 2030:
            return {"ok": False, "error": "invalid_year", "message": "Year must be between 1900 and 2030"}
        
        if not normalized.get("price") or normalized["price"] <= 0:
            return {"ok": False, "error": "invalid_price", "message": "Valid price is required"}

        # Use existing ingest logic
        listing_data = ListingIn(**normalized)
        result = ingest_listing(listing_data)
        
        return {
            "ok": True, 
            "message": "Facebook Marketplace listing processed successfully",
            "listing_id": result.get("listing_id"),
            "match_id": result.get("match_id")
        }
        
    except Exception as e:
        return {"ok": False, "error": "processing_error", "message": str(e)}
