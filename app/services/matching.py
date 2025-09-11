from typing import Optional
from sqlalchemy.orm import Session
from rapidfuzz.fuzz import token_sort_ratio
from app.models import Appraisal, Listing
from app.services.utils import normalize_ymmt

def find_best_appraisal_for_listing(db: Session, listing: Listing) -> tuple[Optional[Appraisal], str, int]:
    # Skip matching if essential fields are missing
    if not listing.make or not listing.model or not listing.year:
        return None, "NONE", 0
        
    ymmt, ymm = normalize_ymmt(listing.year, listing.make, listing.model, listing.trim)

    # Exact YMMT
    q = db.query(Appraisal).filter(Appraisal.year==listing.year,
                                   Appraisal.make.ilike(listing.make),
                                   Appraisal.model.ilike(listing.model))
    if listing.trim:
        q2 = q.filter(Appraisal.trim.ilike(listing.trim))
        exact_ymmt = q2.all()
        if exact_ymmt:
            return exact_ymmt[0], "YMMT", 100

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
