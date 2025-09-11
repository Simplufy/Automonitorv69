
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from app.models import Listing
from typing import Dict, Any, Tuple

def _robust_fit(X, y):
    try:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        preds = X @ coef
        resid = y - preds
        q1, q3 = np.percentile(resid, [25, 75])
        iqr = q3 - q1
        lo, hi = q1 - 1.5*iqr, q3 + 1.5*iqr
        mask = (resid >= lo) & (resid <= hi)
        if mask.sum() < 10:
            return None
        coef2, *_ = np.linalg.lstsq(X[mask], y[mask], rcond=None)
        return coef2
    except Exception:
        return None

def _fit_group(df):
    X = np.column_stack([np.ones(len(df)), df["mileage"].values, df["age"].values if "age" in df.columns else np.zeros(len(df))])
    y = df["price"].values
    return _robust_fit(X, y)

def price_listing_with_market(db: Session, listing: Listing, target_age_std=60.0, target_age_fast=30.0) -> Dict[str, Any]:
    # build comps from DB
    # Use same YMMT/YMM normalization as matching
    year, make, model, trim = listing.year, listing.make, listing.model, listing.trim
    if not (year and make and model):
        return {"note":"insufficient fields for market pricing"}

    # Fetch potentially relevant comps (same make+model same year window +-1)
    q = db.query(Listing).filter(Listing.make.ilike(make), Listing.model.ilike(model), Listing.year.in_([year-1, year, year+1]))
    comps = q.all()
    df = pd.DataFrame([{"id": c.id, "price": c.price, "mileage": c.mileage or 0, "age": 0} for c in comps if c.price is not None])
    if len(df) < 12:
        return {"note":"not enough comps for robust fit","n":len(df)}

    coef = _fit_group(df)
    if coef is None:
        return {"note":"fit failed","n":len(df)}

    b0, b_miles, b_age = coef[0], coef[1], coef[2] if len(coef) > 2 else 0.0

    pred = float(b0 + b_miles*(listing.mileage or 0) + b_age*0.0)
    adj_std  = min(0.0, b_age*(target_age_std - 0.0))
    adj_fast = min(0.0, b_age*(target_age_fast - 0.0))
    std  = float(pred + adj_std)
    fast = float(pred + adj_fast)

    return {
        "n": int(len(df)),
        "b0": float(b0),
        "b_miles": float(b_miles),
        "b_age": float(b_age),
        "predicted_price": pred,
        "recommended_std_60d": std,
        "recommended_fast_30d": fast
    }
