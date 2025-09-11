
#!/usr/bin/env python3
"""
Re-score all existing listings with the updated scoring system.
This will update all MatchResult records to use the new 3-category system.
"""

from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models import Listing, MatchResult
from app.services.matching import find_best_appraisal_for_listing
from app.services.scoring import score_listing
import traceback

def rescore_all_listings():
    """Re-score all listings in the database with the new scoring system"""
    db: Session = SessionLocal()
    try:
        # Get all listings
        listings = db.query(Listing).all()
        print(f"Found {len(listings)} listings to re-score...")
        
        if len(listings) == 0:
            print("No listings found in database!")
            return
        
        updated_count = 0
        error_count = 0
        
        for i, listing in enumerate(listings):
            try:
                print(f"Processing listing {i+1}/{len(listings)}: {listing.year} {listing.make} {listing.model}")
                
                # Find the best appraisal match
                appraisal, level, conf = find_best_appraisal_for_listing(db, listing)
                print(f"  Match: {level} (confidence: {conf})")
                
                # Score the listing
                res = score_listing(listing, appraisal)
                print(f"  Category: {res.get('category')}, Margin: {res.get('margin_percent', 0):.2%}")
                
                # Find or create the MatchResult
                match = db.query(MatchResult).filter(MatchResult.listing_id == listing.id).first()
                
                if match is None:
                    # Create new MatchResult
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
                    print(f"  Created new MatchResult")
                else:
                    # Update existing MatchResult
                    match.appraisal_id = appraisal.id if appraisal else None
                    match.match_level = level
                    match.match_confidence = conf
                    for k, v in res.items():
                        if k == "explanations":
                            match.explanations = v
                        elif hasattr(match, k):
                            setattr(match, k, v)
                    print(f"  Updated existing MatchResult")
                
                updated_count += 1
                
                # Commit every 10 listings to avoid memory issues and show progress
                if updated_count % 10 == 0:
                    db.commit()
                    print(f"Committed {updated_count} listings...")
                    
            except Exception as e:
                error_count += 1
                print(f"  ERROR processing listing {listing.id}: {str(e)}")
                print(f"  Traceback: {traceback.format_exc()}")
                db.rollback()
        
        # Final commit
        try:
            db.commit()
            print(f"Successfully re-scored {updated_count} listings! ({error_count} errors)")
        except Exception as e:
            print(f"Error on final commit: {e}")
            db.rollback()
            return
        
        # Show category breakdown
        categories = db.query(MatchResult.category, db.func.count(MatchResult.id)).group_by(MatchResult.category).all()
        print("\nFinal category breakdown:")
        for category, count in categories:
            print(f"  {category}: {count} listings")
            
    except Exception as e:
        print(f"Error re-scoring listings: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    rescore_all_listings()
