from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, func
from sqlalchemy.exc import OperationalError
from app.db import SessionLocal
from app.models import MatchResult, Listing
from datetime import datetime, timedelta
import time

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@router.get("/listings", response_class=HTMLResponse)
def listings_partial(request: Request, category: str = "PROFITABLE", min_conf: int = 0, 
                     search: str = None, min_price: int = None, max_price: int = None,
                     timeframe: str = None, make_filter: str = None):
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
