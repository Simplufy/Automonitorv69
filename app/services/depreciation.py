import json
import os
import math
from typing import Optional, Dict, Any, List, Tuple
from rapidfuzz import fuzz, process
from app.models import Listing, Appraisal

class DepreciationService:
    """Service for looking up specific trim-level depreciation rates"""
    
    def __init__(self):
        self.depreciation_data: List[Dict[str, Any]] = []
        self.lookup_cache: Dict[str, Dict[str, Any]] = {}
        self._load_data()
    
    def _load_data(self):
        """Load depreciation formulas from JSON file"""
        data_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'depreciation_formulas.json')
        try:
            with open(data_path, 'r') as f:
                self.depreciation_data = json.load(f)
            print(f"✅ Loaded {len(self.depreciation_data)} depreciation formulas")
        except Exception as e:
            print(f"⚠️ Failed to load depreciation data: {e}")
            self.depreciation_data = []
    
    def _create_lookup_key(self, year: int, make: str, model: str, trim: Optional[str] = None) -> str:
        """Create a standardized lookup key"""
        key_parts = [str(year), make.upper(), model.upper()]
        if trim:
            key_parts.append(trim.upper())
        return " ".join(key_parts)
    
    def _extract_trim_info(self, trim_entry: str) -> Tuple[str, Optional[str]]:
        """Extract base vehicle info and body type from Make_Model_Trim field"""
        # Example: "2023 BMW 3 Series 330i xDrive | 4D Sedan"
        if " | " in trim_entry:
            base_info, body_type = trim_entry.split(" | ", 1)
            return base_info.strip(), body_type.strip()
        return trim_entry.strip(), None
    
    def find_depreciation_rate(self, listing: Listing) -> Optional[Dict[str, Any]]:
        """Find the best depreciation rate for a specific listing"""
        if not listing.year or not listing.make or not listing.model:
            return None
        
        # Create cache key
        cache_key = self._create_lookup_key(listing.year, listing.make, listing.model, listing.trim)
        if cache_key in self.lookup_cache:
            return self.lookup_cache[cache_key]
        
        # Look for exact matches first
        exact_matches = []
        fuzzy_candidates = []
        
        for entry in self.depreciation_data:
            base_info, body_type = self._extract_trim_info(entry["Make_Model_Trim"])
            
            # Check if year matches
            if not base_info.startswith(str(listing.year)):
                continue
            
            # Create comparison strings
            listing_string = f"{listing.year} {listing.make} {listing.model}"
            if listing.trim:
                listing_string += f" {listing.trim}"
            
            # Exact match check (case insensitive)
            if listing_string.upper() == base_info.upper():
                exact_matches.append(entry)
            
            # Fuzzy match candidate (same year, make, model)
            base_ymm = " ".join(base_info.split()[:3])  # Year Make Model
            listing_ymm = f"{listing.year} {listing.make} {listing.model}"
            if base_ymm.upper() == listing_ymm.upper():
                fuzzy_candidates.append((entry, base_info))
        
        # Return best exact match (highest sample size)
        if exact_matches:
            best_match = max(exact_matches, key=lambda x: x.get("Sample_Size", 0))
            self.lookup_cache[cache_key] = best_match
            return best_match
        
        # If no exact match, try fuzzy matching on trim within same YMM
        if fuzzy_candidates and listing.trim:
            trim_scores = []
            for entry, base_info in fuzzy_candidates:
                # Extract trim from base_info
                parts = base_info.split()
                if len(parts) > 3:  # Has trim info
                    entry_trim = " ".join(parts[3:])
                    score = fuzz.ratio(listing.trim.upper(), entry_trim.upper())
                    trim_scores.append((score, entry))
            
            if trim_scores:
                # Get best fuzzy match with score > 70 and highest sample size
                good_matches = [(score, entry) for score, entry in trim_scores if score > 70]
                if good_matches:
                    best_match = max(good_matches, key=lambda x: (x[0], x[1].get("Sample_Size", 0)))[1]
                    self.lookup_cache[cache_key] = best_match
                    return best_match
        
        # No good match found
        self.lookup_cache[cache_key] = None
        return None
    
    def _safe_float_to_int(self, value) -> int:
        """
        Safely convert a value to integer, handling NaN, None, and invalid values.
        Returns 0 for any invalid input.
        """
        try:
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return 0
            return int(float(value))
        except (ValueError, TypeError, OverflowError):
            return 0
    
    def calculate_specific_depreciation(self, listing: Listing, appraisal: Optional[Appraisal]) -> Tuple[int, bool]:
        """
        Calculate depreciation using specific trim data if available.
        Returns (adjustment_amount, used_specific_data)
        """
        if not appraisal:
            return 0, False
        
        depreciation_entry = self.find_depreciation_rate(listing)
        if not depreciation_entry:
            return 0, False
        
        total_adjustment = 0
        applied_any_adjustment = False
        
        # Mileage adjustment
        if listing.mileage and appraisal.avg_mileage:
            try:
                mileage_diff = listing.mileage - appraisal.avg_mileage
                mileage_deduction_per_10k = depreciation_entry.get("Mileage_Deduction_per_10k", 0)
                
                # Validate the deduction rate
                if mileage_deduction_per_10k is None or (isinstance(mileage_deduction_per_10k, float) and math.isnan(mileage_deduction_per_10k)):
                    mileage_deduction_per_10k = 0
                else:
                    # Convert to per-mile adjustment then multiply by difference
                    mileage_adjustment = (mileage_diff / 10000) * float(mileage_deduction_per_10k)
                    adjustment = self._safe_float_to_int(mileage_adjustment)
                    if adjustment != 0:  # Only count non-zero adjustments as "applied"
                        total_adjustment += adjustment
                        applied_any_adjustment = True
            except (ValueError, TypeError, ZeroDivisionError):
                # Skip mileage adjustment if data is invalid
                pass
        
        # Age adjustment (if appraisal has base year)
        if hasattr(appraisal, 'year') and appraisal.year and listing.year:
            try:
                age_diff = appraisal.year - listing.year  # Positive if listing is older
                age_deduction_per_year = depreciation_entry.get("Age_Deduction_per_year", 0)
                
                # Validate the deduction rate
                if age_deduction_per_year is None or (isinstance(age_deduction_per_year, float) and math.isnan(age_deduction_per_year)):
                    age_deduction_per_year = 0
                else:
                    age_adjustment = age_diff * float(age_deduction_per_year)
                    adjustment = self._safe_float_to_int(age_adjustment)
                    if adjustment != 0:  # Only count non-zero adjustments as "applied"
                        total_adjustment += adjustment
                        applied_any_adjustment = True
            except (ValueError, TypeError):
                # Skip age adjustment if data is invalid
                pass
        
        # Return True only if we actually applied at least one valid specific adjustment
        return total_adjustment, applied_any_adjustment
    
    def get_depreciation_stats(self) -> Dict[str, Any]:
        """Get statistics about loaded depreciation data"""
        if not self.depreciation_data:
            return {"total_entries": 0}
        
        makes = set()
        years = set()
        total_sample_size = 0
        
        for entry in self.depreciation_data:
            base_info, _ = self._extract_trim_info(entry["Make_Model_Trim"])
            parts = base_info.split()
            if len(parts) >= 2:
                years.add(parts[0])
                makes.add(parts[1])
            total_sample_size += entry.get("Sample_Size", 0)
        
        return {
            "total_entries": len(self.depreciation_data),
            "unique_makes": len(makes),
            "year_range": f"{min(years)} - {max(years)}" if years else "N/A",
            "total_sample_size": total_sample_size,
            "avg_sample_size": total_sample_size / len(self.depreciation_data) if self.depreciation_data else 0
        }

# Global instance
depreciation_service = DepreciationService()