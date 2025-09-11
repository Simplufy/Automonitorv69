import json, csv, os
from sqlalchemy.orm import Session
from app.db import SessionLocal, Base, engine
from app.models import Appraisal, Listing, MatchResult
from app.services.matching import find_best_appraisal_for_listing
from app.services.scoring import score_listing
from datetime import datetime

def seed():
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        # load appraisals
        path_csv = "data/seed_appraisals.csv"
        if os.path.exists(path_csv):
            with open(path_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                db.query(Appraisal).delete()
                for r in reader:
                    db.add(Appraisal(
                        year=int(r["year"]), make=r["make"], model=r["model"],
                        trim=(r["trim"] or None), benchmark_price=int(r["benchmark_price"]),
                        avg_mileage=int(r["avg_mileage"]) if r.get("avg_mileage") else None,
                        notes=r.get("notes")
                    ))
                db.commit()

        # load listings & compute matches
        path_json = "data/seed_listings.json"
        if os.path.exists(path_json):
            with open(path_json, "r", encoding="utf-8") as f:
                items = json.load(f)
            db.query(MatchResult).delete()
            db.query(Listing).delete()
            db.commit()
            for it in items:
                lst = Listing(**it)
                db.add(lst); db.commit(); db.refresh(lst)
                app, level, conf = find_best_appraisal_for_listing(db, lst)
                res = score_listing(lst, app)
                m = MatchResult(listing_id=lst.id, appraisal_id=app.id if app else None,
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
                db.add(m); db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    seed()
