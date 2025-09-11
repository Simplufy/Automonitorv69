from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from app.db import SessionLocal
from app.schemas import ListingIn
from app.models import Listing, MatchResult
from app.services.matching import find_best_appraisal_for_listing
from app.services.scoring import score_listing
from app.services.llm_parser import VehicleParser
from app.services.market_pricing import price_listing_with_market

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
