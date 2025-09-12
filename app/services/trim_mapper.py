"""
Universal trim mapping service for accurate vehicle appraisal matching.
Implements deterministic + constrained fuzzy matching with caching.
"""
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy.orm import Session
from rapidfuzz.fuzz import token_set_ratio
import re
import json
from dataclasses import dataclass
from app.models import CanonicalTrim, TrimAlias, PatternType, Appraisal
import logging

logger = logging.getLogger(__name__)

@dataclass
class TrimMatchResult:
    canonical_trim: str
    confidence: int
    match_type: str  # "exact", "alias", "fuzzy", "none"
    original_listing_trim: str

class TrimMapper:
    """Universal trim mapping service with caching and intelligent matching"""
    
    def __init__(self):
        self._cache: Dict[str, Dict] = {}
        self._cache_ttl = 3600  # 1 hour cache TTL
        
    def normalize_trim_text(self, trim: str) -> str:
        """Normalize trim text for consistent matching"""
        if not trim:
            return ""
            
        # Convert to lowercase
        normalized = trim.lower()
        
        # Standardize common abbreviations and terms
        replacements = {
            # Common abbreviations
            'plus': 'plus',
            '+': 'plus',
            'premium plus': 'premium plus',
            'prem plus': 'premium plus',
            
            # Drivetrain terms (often optional in appraisals)
            'awd': '',
            'fwd': '',
            'rwd': '',
            '4wd': '',
            'xdrive': '',
            'quattro': '',
            '4matic': '',
            
            # Remove common filler words
            ' package': '',
            ' pkg': '',
            ' edition': '',
            ' model': '',
        }
        
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        
        # Clean up whitespace and punctuation
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        normalized = ' '.join(normalized.split())  # Normalize whitespace
        
        return normalized.strip()
    
    def get_candidates(self, db: Session, make: str, model: str, year: int) -> List[CanonicalTrim]:
        """Get candidate canonical trims for the given vehicle"""
        cache_key = f"{make.lower()}_{model.lower()}_{year}"
        
        if cache_key in self._cache:
            candidates_data = self._cache[cache_key]
            # Convert back to CanonicalTrim objects (simplified caching)
            return db.query(CanonicalTrim).filter(
                CanonicalTrim.make.ilike(make),
                CanonicalTrim.model.ilike(model),
                CanonicalTrim.year_start <= year,
                CanonicalTrim.year_end >= year,
                CanonicalTrim.active == True
            ).all()
        
        # Query database for candidates
        candidates = db.query(CanonicalTrim).filter(
            CanonicalTrim.make.ilike(make),
            CanonicalTrim.model.ilike(model),
            CanonicalTrim.year_start <= year,
            CanonicalTrim.year_end >= year,
            CanonicalTrim.active == True
        ).all()
        
        # Cache the results (simplified)
        self._cache[cache_key] = True
        
        return candidates
    
    def find_exact_alias_match(self, db: Session, listing_trim: str, candidates: List[CanonicalTrim]) -> Optional[CanonicalTrim]:
        """Find exact alias matches for the listing trim"""
        if not listing_trim or not candidates:
            return None
            
        candidate_ids = [c.id for c in candidates]
        
        # Try exact matches first
        exact_alias = db.query(TrimAlias).filter(
            TrimAlias.canonical_id.in_(candidate_ids),
            TrimAlias.alias.ilike(listing_trim),
            TrimAlias.pattern_type == PatternType.EXACT,
            TrimAlias.active == True
        ).order_by(TrimAlias.priority).first()
        
        if exact_alias:
            return db.query(CanonicalTrim).get(exact_alias.canonical_id)
            
        # Try contains matches - check if listing_trim contains the alias
        normalized_listing = self.normalize_trim_text(listing_trim)
        contains_aliases = db.query(TrimAlias).filter(
            TrimAlias.canonical_id.in_(candidate_ids),
            TrimAlias.pattern_type == PatternType.CONTAINS,
            TrimAlias.active == True
        ).order_by(TrimAlias.priority).all()
        
        contains_alias = None
        for alias in contains_aliases:
            normalized_alias = self.normalize_trim_text(alias.alias)
            if normalized_alias in normalized_listing:
                contains_alias = alias
                break
        
        if contains_alias:
            return db.query(CanonicalTrim).get(contains_alias.canonical_id)
            
        return None
    
    def find_fuzzy_match(self, listing_trim: str, candidates: List[CanonicalTrim], threshold: int = 85) -> Optional[Tuple[CanonicalTrim, int]]:
        """Find best fuzzy match within candidate set"""
        if not listing_trim or not candidates:
            return None
            
        normalized_listing = self.normalize_trim_text(listing_trim)
        best_match = None
        best_score = 0
        
        for candidate in candidates:
            normalized_canonical = self.normalize_trim_text(candidate.canonical_trim)
            
            # Use token_set_ratio for better handling of partial matches
            score = token_set_ratio(normalized_listing, normalized_canonical)
            
            if score > best_score and score >= threshold:
                best_score = score
                best_match = candidate
                
        return (best_match, best_score) if best_match else None
    
    def map_trim_to_canonical(self, db: Session, make: str, model: str, year: int, listing_trim: str) -> TrimMatchResult:
        """
        Map a listing trim to canonical trim using the complete matching pipeline
        """
        if not listing_trim:
            return TrimMatchResult(
                canonical_trim="",
                confidence=0,
                match_type="none",
                original_listing_trim=listing_trim or ""
            )
        
        try:
            # Step 1: Get candidate canonical trims for this make/model/year
            candidates = self.get_candidates(db, make, model, year)
            
            if not candidates:
                logger.debug(f"No canonical trims found for {year} {make} {model}")
                return TrimMatchResult(
                    canonical_trim="",
                    confidence=0,
                    match_type="none",
                    original_listing_trim=listing_trim
                )
            
            # Step 2: Try exact alias match first (deterministic)
            exact_match = self.find_exact_alias_match(db, listing_trim, candidates)
            if exact_match:
                return TrimMatchResult(
                    canonical_trim=exact_match.canonical_trim,
                    confidence=100,
                    match_type="alias",
                    original_listing_trim=listing_trim
                )
            
            # Step 3: Try constrained fuzzy matching within candidates only
            fuzzy_result = self.find_fuzzy_match(listing_trim, candidates, threshold=88)
            if fuzzy_result:
                match, score = fuzzy_result
                return TrimMatchResult(
                    canonical_trim=match.canonical_trim,
                    confidence=score,
                    match_type="fuzzy",
                    original_listing_trim=listing_trim
                )
            
            # No match found
            logger.debug(f"No trim mapping found for {year} {make} {model} '{listing_trim}'")
            return TrimMatchResult(
                canonical_trim="",
                confidence=0,
                match_type="none", 
                original_listing_trim=listing_trim
            )
            
        except Exception as e:
            logger.error(f"Error in trim mapping for {year} {make} {model} '{listing_trim}': {e}")
            return TrimMatchResult(
                canonical_trim="",
                confidence=0,
                match_type="none",
                original_listing_trim=listing_trim
            )

# Global instance
trim_mapper = TrimMapper()