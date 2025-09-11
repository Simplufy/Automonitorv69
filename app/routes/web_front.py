from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.db import SessionLocal
from app.models import MatchResult, Listing

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@router.get("/listings", response_class=HTMLResponse)
def listings_partial(request: Request, category: str = "PROFITABLE", min_conf: int = 0, 
                     search: str = None, min_price: int = None, max_price: int = None):
    db: Session = SessionLocal()
    try:
        q = db.query(MatchResult).join(Listing, MatchResult.listing_id==Listing.id).filter(MatchResult.category==category)
        
        if min_conf:
            q = q.filter(MatchResult.match_confidence>=min_conf)
        
        # Search filter for make/model
        if search:
            search_term = f"%{search.lower()}%"
            q = q.filter(
                (Listing.make.ilike(search_term)) |
                (Listing.model.ilike(search_term)) |
                ((Listing.make + ' ' + Listing.model).ilike(search_term)) |
                (Listing.trim.ilike(search_term))
            )
        
        # Price range filters
        if min_price:
            q = q.filter(Listing.price >= min_price)
        
        if max_price:
            q = q.filter(Listing.price <= max_price)
        
        q = q.order_by(desc(MatchResult.margin_percent))
        rows = q.limit(200).all()
        return templates.TemplateResponse("partials/listing_cards.html", {"request": request, "rows": rows})
    finally:
        db.close()
