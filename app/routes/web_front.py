from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, func
from sqlalchemy.exc import OperationalError
from app.db import SessionLocal
from app.models import MatchResult, Listing
from datetime import datetime, timedelta
import time
from typing import Optional

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@router.get("/listings", response_class=HTMLResponse)
def listings_partial(request: Request, category: str = "PROFITABLE", min_conf: int = 0, 
                     search: Optional[str] = None, min_price: Optional[int] = None, max_price: Optional[int] = None,
                     timeframe: Optional[str] = None, make_filter: Optional[str] = None):
    # Retry logic for database connection issues
    max_retries = 3
    for attempt in range(max_retries):
        db: Session = SessionLocal()
        try:
            q = db.query(MatchResult).join(Listing, MatchResult.listing_id==Listing.id).filter(MatchResult.category==category)
            
            if min_conf:
                q = q.filter(MatchResult.match_confidence>=min_conf)
        
            # Time-based filtering
            if timeframe:
                now = datetime.utcnow()
                if timeframe == "24h":
                    cutoff = now - timedelta(hours=24)
                elif timeframe == "3d":
                    cutoff = now - timedelta(days=3)
                elif timeframe == "7d":
                    cutoff = now - timedelta(days=7)
                elif timeframe == "30d":
                    cutoff = now - timedelta(days=30)
                else:
                    cutoff = None
                
                if cutoff:
                    q = q.filter(Listing.ingested_at >= cutoff)
            
            # Brand/make filter
            if make_filter and make_filter != "all":
                q = q.filter(Listing.make.ilike(f"%{make_filter}%"))
            
            # Search filter for make/model (with NULL-safe concatenation)
            if search:
                search_term = f"%{search.lower()}%"
                q = q.filter(
                    (func.coalesce(Listing.make, '').ilike(search_term)) |
                    (func.coalesce(Listing.model, '').ilike(search_term)) |
                    (func.concat(func.coalesce(Listing.make, ''), ' ', func.coalesce(Listing.model, '')).ilike(search_term)) |
                    (func.coalesce(Listing.trim, '').ilike(search_term))
                )
            
            # Price range filters
            if min_price:
                q = q.filter(Listing.price >= min_price)
            
            if max_price:
                q = q.filter(Listing.price <= max_price)
            
            q = q.order_by(desc(MatchResult.margin_percent))
            rows = q.limit(200).all()
            return templates.TemplateResponse("partials/listing_cards.html", {"request": request, "rows": rows})
            
        except OperationalError as e:
            db.close()
            if attempt < max_retries - 1:
                print(f"Database connection error on attempt {attempt + 1}, retrying in {attempt + 1} seconds...")
                time.sleep(attempt + 1)  # Exponential backoff
                continue
            else:
                print(f"Database connection failed after {max_retries} attempts: {e}")
                # Return empty response on final failure
                return templates.TemplateResponse("partials/listing_cards.html", {"request": request, "rows": []})
        except Exception as e:
            db.close()
            print(f"Unexpected error in listings_partial: {e}")
            return templates.TemplateResponse("partials/listing_cards.html", {"request": request, "rows": []})
        finally:
            db.close()
            break  # Exit retry loop on success

@router.post("/api/refresh-data")
def refresh_data_manual():
    """Manual trigger to rescore all recent listings from last 24 hours"""
    from app.routes.api_ingest import find_best_appraisal_for_listing
    from app.services.scoring import score_listing
    
    # Initialize result tracking
    result = {
        "ok": True,
        "message": "Data refresh completed",
        "rescoring": {"ok": False, "processed": 0, "error": None},
        "timestamp": datetime.utcnow().isoformat()
    }
    
    db: Session = SessionLocal()
    try:
        # Rescore all recent listings (last 24 hours)
        twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
        
        recent_listings = db.query(Listing).filter(
            Listing.ingested_at >= twenty_four_hours_ago
        ).all()
        
        # Delete existing match results for these listings
        if recent_listings:
            deleted_matches = db.query(MatchResult).filter(
                MatchResult.listing_id.in_([l.id for l in recent_listings])
            ).delete(synchronize_session=False)
            db.commit()
        
        processed_count = 0
        failed_count = 0
        
        # Rescore each listing
        for listing in recent_listings:
            try:
                appraisal, level, conf = find_best_appraisal_for_listing(db, listing)
                res = score_listing(listing, appraisal)
                
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
                    explanations=res.get("explanations")
                )
                db.add(match)
                processed_count += 1
                
                # Commit in batches
                if processed_count % 50 == 0:
                    db.commit()
                
            except Exception as e:
                print(f"Failed to rescore listing {listing.id}: {e}")
                failed_count += 1
        
        db.commit()
        result["rescoring"] = {"ok": True, "processed": processed_count, "failed": failed_count, "error": None}
        result["message"] = f"Successfully rescored {processed_count} listings from last 24 hours"
        
        if failed_count > 0:
            result["message"] += f" ({failed_count} failed)"
        
        return result
        
    except Exception as e:
        db.rollback()
        result["ok"] = False
        result["rescoring"]["error"] = str(e)
        result["message"] = f"Data refresh failed: {str(e)}"
        return result
    finally:
        db.close()

@router.get("/api/makes")
def get_available_makes():
    """Get list of available vehicle makes for filter dropdown"""
    # Retry logic for database connection issues
    max_retries = 3
    for attempt in range(max_retries):
        db: Session = SessionLocal()
        try:
            # Get distinct makes that have match results
            makes = db.query(Listing.make).join(MatchResult, MatchResult.listing_id == Listing.id).distinct().order_by(Listing.make).all()
            make_list = [make[0] for make in makes if make[0]]
            return {"makes": make_list}
        except OperationalError as e:
            db.close()
            if attempt < max_retries - 1:
                print(f"Database connection error in get_available_makes on attempt {attempt + 1}, retrying...")
                time.sleep(attempt + 1)
                continue
            else:
                print(f"Database connection failed after {max_retries} attempts: {e}")
                return {"makes": []}
        except Exception as e:
            db.close()
            print(f"Unexpected error in get_available_makes: {e}")
            return {"makes": []}
        finally:
            db.close()
            break
