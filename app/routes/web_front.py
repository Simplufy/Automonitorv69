from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, func, or_
from sqlalchemy.exc import OperationalError
from app.db import SessionLocal
from app.models import MatchResult, Listing
from datetime import datetime, timedelta
import time
from typing import Optional
import httpx
import hashlib
import base64

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/listings", response_class=HTMLResponse)
def listings_partial(request: Request, category: str = "PROFITABLE", min_conf: int = 0, 
                     search: Optional[str] = None, min_price: Optional[int] = None, max_price: Optional[int] = None,
                     timeframe: Optional[str] = None, make_filter: Optional[str] = None, source: Optional[str] = None):
    db: Session = SessionLocal()
    try:
        # Query for listings
        q = db.query(MatchResult).join(Listing, MatchResult.listing_id==Listing.id).filter(MatchResult.category==category)
        
        # Time-based filtering  
        if timeframe:
            now = datetime.utcnow()
            if timeframe == "24h":
                cutoff = now - timedelta(hours=24)
                q = q.filter(Listing.ingested_at >= cutoff)
            elif timeframe == "3d":
                cutoff = now - timedelta(days=3)
                q = q.filter(Listing.ingested_at >= cutoff)
            elif timeframe == "7d":
                cutoff = now - timedelta(days=7)
                q = q.filter(Listing.ingested_at >= cutoff)
            elif timeframe == "30d":
                cutoff = now - timedelta(days=30)
                q = q.filter(Listing.ingested_at >= cutoff)
        
        # Source/platform filtering
        if source:
            q = q.filter(Listing.source == source)
        
        # Price filtering
        if min_price:
            q = q.filter(Listing.price >= min_price)
        if max_price:
            q = q.filter(Listing.price <= max_price)
        
        # Search filtering
        if search:
            search_term = f"%{search.lower()}%"
            q = q.filter(or_(
                func.lower(Listing.make).like(search_term),
                func.lower(Listing.model).like(search_term),
                func.lower(Listing.trim).like(search_term),
                func.concat(func.lower(Listing.make), ' ', func.lower(Listing.model)).like(search_term)
            ))
        
        # Get results
        q = q.order_by(desc(MatchResult.margin_percent))
        rows = q.limit(200).all()
        
        # Return template response
        return templates.TemplateResponse("partials/listing_cards.html", {"request": request, "rows": rows})
        
    except Exception as e:
        print(f"Error in listings_partial: {e}")
        import traceback
        print(traceback.format_exc())
        return f"<div>Error: {e}</div>"
    finally:
        db.close()

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

@router.get("/proxy-image")
async def proxy_image(url: str):
    """Proxy images to bypass CORS restrictions"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Set headers to mimic a regular browser request
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            }
            
            response = await client.get(url, headers=headers, follow_redirects=True)
            
            if response.status_code == 200:
                content_type = response.headers.get('content-type', 'image/jpeg')
                
                # Return the image with proper headers
                return Response(
                    content=response.content,
                    media_type=content_type,
                    headers={
                        'Cache-Control': 'public, max-age=3600',  # Cache for 1 hour
                        'Access-Control-Allow-Origin': '*'
                    }
                )
            else:
                # Return a simple placeholder if image fetch fails
                return Response(
                    content="data:image/svg+xml;base64," + base64.b64encode(
                        f'<svg width="200" height="150" xmlns="http://www.w3.org/2000/svg"><rect width="200" height="150" fill="#f0f0f0"/><text x="50%" y="50%" text-anchor="middle" dy=".3em" font-family="Arial" font-size="14" fill="#666">🚗 Vehicle</text></svg>'.encode()
                    ).decode(),
                    media_type="image/svg+xml"
                )
                
    except Exception as e:
        print(f"Error proxying image {url}: {e}")
        # Return a simple placeholder on error
        return Response(
            content="data:image/svg+xml;base64," + base64.b64encode(
                f'<svg width="200" height="150" xmlns="http://www.w3.org/2000/svg"><rect width="200" height="150" fill="#f0f0f0"/><text x="50%" y="50%" text-anchor="middle" dy=".3em" font-family="Arial" font-size="14" fill="#666">🚗 Vehicle</text></svg>'.encode()
            ).decode(),
            media_type="image/svg+xml"
        )
