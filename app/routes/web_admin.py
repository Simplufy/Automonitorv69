from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import csv, io, json
from datetime import datetime

from app.db import SessionLocal
from app.models import Appraisal, Listing, MatchResult
from app.config import settings
from app.services.apify_client import fetch_and_store_multi_source
from app.services.depreciation import depreciation_service
from app.services.matching import find_best_appraisal_for_listing
from app.services.scoring import score_listing_async

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")

def authed(request: Request) -> bool:
    return request.cookies.get("admin") == settings.ADMIN_PASSPHRASE

@router.get("", response_class=HTMLResponse, name="admin_home")
def home(request: Request):
    if not authed(request):
        return templates.TemplateResponse("admin_login.html", {"request": request})
    
    # Get appraisal database stats
    db: Session = SessionLocal()
    try:
        appraisal_count = db.query(Appraisal).count()
        latest_appraisal = db.query(Appraisal).order_by(Appraisal.updated_at.desc()).first()
        listing_count = db.query(Listing).count()
        latest_listing = db.query(Listing).order_by(Listing.ingested_at.desc()).first()
        
        appraisal_stats = {
            "count": appraisal_count,
            "latest_update": latest_appraisal.updated_at if latest_appraisal else None,
            "sample_entry": f"{latest_appraisal.year} {latest_appraisal.make} {latest_appraisal.model}" if latest_appraisal else None
        }
        
        listing_stats = {
            "count": listing_count,
            "latest_ingest": latest_listing.ingested_at if latest_listing else None
        }
        
        return templates.TemplateResponse("admin_home.html", {
            "request": request, 
            "appraisal_stats": appraisal_stats,
            "listing_stats": listing_stats
        })
    finally:
        db.close()

@router.post("/login")
def login(request: Request, passphrase: str = Form(...)):
    if passphrase == settings.ADMIN_PASSPHRASE:
        resp = RedirectResponse(url="/admin", status_code=303)
        resp.set_cookie("admin", passphrase, httponly=True)
        return resp
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/appraisals", response_class=HTMLResponse)
def appraisals_page(request: Request):
    if not authed(request):
        return RedirectResponse(url="/admin", status_code=303)
    db: Session = SessionLocal()
    try:
        rows = db.query(Appraisal).order_by(Appraisal.year, Appraisal.make, Appraisal.model, Appraisal.trim).all()
        return templates.TemplateResponse("admin_appraisals.html", {"request": request, "rows": rows})
    finally:
        db.close()

@router.post("/appraisals/upload_csv")
def upload_appraisals_csv(request: Request, file: UploadFile = File(...)):
    if not authed(request):
        return RedirectResponse(url="/admin", status_code=303)
    db: Session = SessionLocal()
    try:
        content = file.file.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
        db.query(Appraisal).delete()
        for row in reader:
            if not row.get("year") or not row.get("make") or not row.get("model") or not row.get("benchmark_price"):
                continue
            app = Appraisal(
                year=int(row["year"]), make=row["make"], model=row["model"],
                trim=(row.get("trim") or None),
                benchmark_price=int(row["benchmark_price"]),
                avg_mileage=int(row["avg_mileage"]) if row.get("avg_mileage") else None,
                notes=row.get("notes")
            )
            db.add(app)
        db.commit()
        return RedirectResponse(url="/admin/appraisals", status_code=303)
    finally:
        db.close()

@router.get("/appraisals/export_csv")
def export_appraisals_csv():
    db: Session = SessionLocal()
    try:
        output = io.StringIO()
        w = csv.writer(output)
        w.writerow(["year","make","model","trim","benchmark_price","avg_mileage","notes"])
        for a in db.query(Appraisal).all():
            w.writerow([a.year,a.make,a.model,a.trim or "",a.benchmark_price,a.avg_mileage or "",a.notes or ""])
        return PlainTextResponse(output.getvalue(), media_type="text/csv")
    finally:
        db.close()

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    if not authed(request):
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse("admin_settings.html", {"request": request, "settings": settings})

@router.post("/settings")
def update_settings(request: Request,
                    SHIPPING_RATE_PER_MILE: float = Form(...),
                    DEST_LAT: float = Form(...),
                    DEST_LON: float = Form(...),
                    PROFIT_MIN_PCT: float = Form(...),
                    MAYBE_MIN_PCT: float = Form(...),
                    PACK_TIERS_JSON: str = Form(...)):
    if not authed(request):
        return RedirectResponse(url="/admin", status_code=303)
    settings.SHIPPING_RATE_PER_MILE = float(SHIPPING_RATE_PER_MILE)
    settings.DEST_LAT = float(DEST_LAT)
    settings.DEST_LON = float(DEST_LON)
    settings.PROFIT_MIN_PCT = float(PROFIT_MIN_PCT)
    settings.MAYBE_MIN_PCT = float(MAYBE_MIN_PCT)
    try:
        tiers = json.loads(PACK_TIERS_JSON)
        assert isinstance(tiers, list)
        settings.PACK_TIERS = tiers
    except Exception:
        pass
    return RedirectResponse(url="/admin/settings", status_code=303)

@router.post("/fetch_apify")
async def fetch_apify_now(request: Request):
    if not authed(request):
        return RedirectResponse(url="/admin", status_code=303)
    db: Session = SessionLocal()
    try:
        # Use Cars.com fetch for new listings
        inserted, skipped = await fetch_and_store_multi_source(db, runs_to_scan=2, items_per_run_limit=None)
        print(f"Admin fetch complete: {inserted} new listings, {skipped} skipped")
        return RedirectResponse(url="/admin", status_code=303)
    finally:
        db.close()
@router.get("/raw-listings", response_class=HTMLResponse)
def raw_listings_page(request: Request):
    if not authed(request):
        return RedirectResponse(url="/admin", status_code=303)
    db: Session = SessionLocal()
    try:
        listings = db.query(Listing).order_by(Listing.ingested_at.desc()).limit(100).all()
        return templates.TemplateResponse("admin_raw_listings.html", {
            "request": request, 
            "listings": listings
        })
    finally:
        db.close()

@router.get("/test-apify", response_class=PlainTextResponse)
def test_apify_connection(request: Request):
    if not authed(request):
        return "Not authenticated"
    
    token = settings.APIFY_TOKEN
    actor_id = settings.APIFY_CARSCOM_ACTOR_ID
    
    result = []
    result.append(f"APIFY_TOKEN: {'SET' if token else 'NOT SET'}")
    result.append(f"APIFY_CARSCOM_ACTOR_ID: {actor_id}")
    
    if not token:
        result.append("\nERROR: APIFY_TOKEN is not set in secrets")
        return "\n".join(result)
    
    if not actor_id:
        result.append("\nERROR: APIFY_CARSCOM_ACTOR_ID is not set in secrets")
        return "\n".join(result)
    
    # Test basic API access
    import httpx
    try:
        with httpx.Client(timeout=10) as client:
            # Test if we can access the API at all
            result.append(f"\nTesting API access...")
            test_url = f"https://api.apify.com/v2/acts?token={token}&limit=1"
            resp = client.get(test_url)
            result.append(f"API Status: {resp.status_code}")
            
            if resp.status_code == 200:
                result.append("✓ API access successful")
            else:
                result.append(f"✗ API access failed: {resp.text}")
                return "\n".join(result)
            
            # Test specific actor access
            result.append(f"\nTesting actor access...")
            actor_url = f"https://api.apify.com/v2/acts/{actor_id}?token={token}"
            actor_resp = client.get(actor_url)
            result.append(f"Actor Status: {actor_resp.status_code}")
            
            if actor_resp.status_code == 200:
                result.append("✓ Actor access successful")
                actor_data = actor_resp.json()
                result.append(f"Actor Name: {actor_data.get('data', {}).get('name', 'Unknown')}")
            else:
                result.append(f"✗ Actor access failed: {actor_resp.text}")
                result.append(f"URL tested: {actor_url}")
                
            # Test runs endpoint
            result.append(f"\nTesting runs endpoint...")
            runs_url = f"https://api.apify.com/v2/acts/{actor_id}/runs?token={token}&limit=1"
            runs_resp = client.get(runs_url)
            result.append(f"Runs Status: {runs_resp.status_code}")
            
            if runs_resp.status_code == 200:
                runs_data = runs_resp.json()
                total_runs = runs_data.get('data', {}).get('total', 0)
                result.append(f"✓ Runs access successful - Total runs: {total_runs}")
            else:
                result.append(f"✗ Runs access failed: {runs_resp.text}")
    
    except Exception as e:
        result.append(f"\nException occurred: {str(e)}")
    
    return "\n".join(result)

@router.get("/depreciation-stats", response_class=PlainTextResponse)
def depreciation_stats(request: Request):
    if not authed(request):
        return "Not authenticated"
    
    stats = depreciation_service.get_depreciation_stats()
    
    result = []
    result.append("=== DEPRECIATION DATA STATS ===")
    result.append(f"Total Entries: {stats['total_entries']}")
    result.append(f"Unique Makes: {stats['unique_makes']}")
    result.append(f"Year Range: {stats['year_range']}")
    result.append(f"Total Sample Size: {stats['total_sample_size']:,}")
    result.append(f"Average Sample Size: {stats['avg_sample_size']:.1f}")
    
    if stats['total_entries'] > 0:
        result.append("\n=== SAMPLE ENTRIES ===")
        # Show first few entries as examples
        for i, entry in enumerate(depreciation_service.depreciation_data[:5]):
            result.append(f"{i+1}. {entry.get('Make_Model_Trim', 'Unknown')}")
            result.append(f"   Mileage: ${entry.get('Mileage_Deduction_per_10k', 0):,.0f}/10k miles")
            result.append(f"   Age: ${entry.get('Age_Deduction_per_year', 0):,.0f}/year")
            result.append(f"   Sample Size: {entry.get('Sample_Size', 0)}")
            result.append(f"   R²: {entry.get('R2', 0):.3f}")
            result.append("")
    
    return "\n".join(result)
