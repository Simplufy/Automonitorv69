from typing import Optional
from sqlalchemy.orm import Session
from rapidfuzz.fuzz import token_sort_ratio
from app.models import Appraisal, Listing
from app.services.utils import normalize_ymmt

def normalize_trim_for_matching(make: str, model: str, trim: str) -> str:
    """Legacy function - replaced by TrimMapper service"""
    # Import here to avoid circular imports
    from app.services.trim_mapper import trim_mapper
    from app.db import SessionLocal
    
    if not trim or not make or not model:
        return trim
    
    # Use TrimMapper for intelligent mapping
    db = SessionLocal()
    try:
        # For now, extract year from context (this is a transitional function)
        # In practice, we'll call TrimMapper directly from the main matching logic
        result = trim_mapper.map_trim_to_canonical(db, make, model, 2021, trim)  # Default year
        return result.canonical_trim if result.canonical_trim else trim
    finally:
        db.close()

def find_best_appraisal_for_listing(db: Session, listing: Listing) -> tuple[Optional[Appraisal], str, int]:
    # Skip matching if essential fields are missing
    if not listing.make or not listing.model or not listing.year:
        return None, "NONE", 0
        
    ymmt, ymm = normalize_ymmt(listing.year, listing.make, listing.model, listing.trim)

    # Exact YMMT with intelligent trim mapping
    q = db.query(Appraisal).filter(Appraisal.year==listing.year,
                                   Appraisal.make.ilike(listing.make),
                                   Appraisal.model.ilike(listing.model))
    if listing.trim:
        # First try exact match
        q2 = q.filter(Appraisal.trim.ilike(listing.trim))
        exact_ymmt = q2.all()
        if exact_ymmt:
            return exact_ymmt[0], "YMMT", 100
            
        # Then use TrimMapper for intelligent mapping
        from app.services.trim_mapper import trim_mapper
        trim_result = trim_mapper.map_trim_to_canonical(db, listing.make, listing.model, listing.year, listing.trim)
        
        if trim_result.canonical_trim and trim_result.confidence >= 85:
            q3 = q.filter(Appraisal.trim.ilike(trim_result.canonical_trim))
            mapped_ymmt = q3.all()
            if mapped_ymmt:
                # Use the confidence from TrimMapper as match confidence
                confidence = min(trim_result.confidence, 100)
                return mapped_ymmt[0], "YMMT", confidence

    # Exact YMM (trim NULL)
    exact_ymm = db.query(Appraisal).filter(Appraisal.year==listing.year,
                                           Appraisal.make.ilike(listing.make),
                                           Appraisal.model.ilike(listing.model),
                                           Appraisal.trim.is_(None)).all()
    if exact_ymm:
        return exact_ymm[0], "YMM", 100

    # Fuzzy fallback
    best = (None, "NONE", 0)
    for app in db.query(Appraisal).all():
        a_ymmt, a_ymm = normalize_ymmt(app.year, app.make, app.model, app.trim)
        s1 = token_sort_ratio(ymmt, a_ymmt)
        s2 = token_sort_ratio(ymm, a_ymm)
        score = max(s1, s2)
        level = "YMMT" if s1 >= s2 else "YMM"
        if score > best[2]:
            best = (app, level, score)
    app, level, score = best
    if app is None:
        return None, "NONE", 0
    if score >= 90:
        return app, level, score
    elif score >= 80:
        return app, level, score
    else:
        return None, "NONE", score
