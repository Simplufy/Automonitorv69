
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.services.apify_client import fetch_and_store_multi_source

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/admin/fetch")
async def manual_fetch(request: Request, db: Session = Depends(get_db)):
    """
    Manually fetch latest items from Apify and upsert/score them.
    Redirects back to /admin with ?fetched=X&skipped=Y so the banner shows.
    """
    # Fetch from Cars.com actor with 5 most recent runs
    inserted, skipped = await fetch_and_store_multi_source(db, runs_to_scan=5, items_per_run_limit=None)
    # Redirect to admin page with query parameters
    url = str(request.url_for("admin_home"))
    return RedirectResponse(f"{url}?fetched={inserted}&skipped={skipped}", status_code=303)
