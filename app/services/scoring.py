from typing import Optional, Dict, Any
import asyncio
from app.config import settings
from app.models import Listing, Appraisal
from app.services.geo import haversine_miles, geocode_location, extract_area_code_from_phone, geocode_area_code

def pack_cost(price: int) -> int:
    for tier in settings.PACK_TIERS:
        if tier["min"] <= price <= tier["max"]:
            return int(tier["cost"])
    return 0

def categorize_vehicle(listing: Listing) -> str:
    """
    Categorize vehicle for mileage adjustment purposes.
    Returns: 'supercar', 'coupe_convertible', 'suv', or 'sedan'
    """
    # Check if it's a supercar/extreme lux (over $70k)
    if listing.price >= settings.MILEAGE_SUPERCAR_PRICE_THRESHOLD:
        return 'supercar'
    
    # Check body style for coupe/convertible (2-door vehicles)
    body_style = getattr(listing, 'body_style', '').lower()
    if any(style in body_style for style in ['coupe', 'convertible', 'roadster', '2dr', '2-door']):
        return 'coupe_convertible'
    
    # Check for SUV/truck variants
    if any(style in body_style for style in ['suv', 'truck', 'crossover', 'utility']):
        return 'suv'
    
    # Default to sedan for everything else
    return 'sedan'

def calculate_mileage_adjustment(listing: Listing, appraisal: Appraisal) -> int:
    """
    Calculate mileage-based price adjustment based on vehicle category and mileage differential.
    Returns adjustment amount (negative = penalty, positive = bonus)
    """
    if not listing.mileage or not appraisal.avg_mileage:
        return 0
    
    mileage_diff = listing.mileage - appraisal.avg_mileage
    vehicle_category = categorize_vehicle(listing)
    
    # Supercars/Extreme Lux (over $70k): ±$3,000 per 5,000 miles
    if vehicle_category == 'supercar':
        increments = mileage_diff / 5000
        return int(-increments * settings.MILEAGE_SUPERCAR_ADJUSTMENT_PER_5K)
    
    # High-mileage coupes/convertibles (over 45k miles): -$2,000 per 5,000 miles over benchmark
    if vehicle_category == 'coupe_convertible' and listing.mileage > settings.MILEAGE_HIGH_MILE_THRESHOLD:
        if mileage_diff > 0:  # Only apply penalty, no bonus for being under
            increments = mileage_diff / 5000
            return int(-increments * settings.MILEAGE_HIGH_MILE_ADJUSTMENT_PER_5K)
    
    # SUVs: ±$1,500 per 10,000 miles
    elif vehicle_category == 'suv':
        increments = mileage_diff / 10000
        return int(-increments * settings.MILEAGE_SUV_ADJUSTMENT_PER_10K)
    
    # Normal sedans (under $70k): ±$2,000 per 10,000 miles
    else:  # sedan or fallback
        increments = mileage_diff / 10000
        return int(-increments * settings.MILEAGE_SEDAN_ADJUSTMENT_PER_10K)
    
    return 0

def recon_cost(year: int, mileage: Optional[int]) -> int:
    if mileage is not None and mileage <= settings.RECON_NEW_MILES_MAX:
        return settings.RECON_NEW_COST
    if year >= settings.RECON_OLD_YEAR_THRESHOLD:
        return settings.RECON_OLD_COST
    return settings.RECON_STANDARD_COST

async def shipping_cost(listing: Listing) -> tuple[float, float, bool]:
    # First try to use existing lat/lon coordinates
    if listing.lat is not None and listing.lon is not None:
        miles = haversine_miles(listing.lat, listing.lon, settings.DEST_LAT, settings.DEST_LON)
        return miles, miles * settings.SHIPPING_RATE_PER_MILE, False
    
    # If no coordinates available, try to geocode from zip code or location
    if listing.zip:
        coords = await geocode_location(listing.zip)
        if coords:
            lat, lon = coords
            miles = haversine_miles(lat, lon, settings.DEST_LAT, settings.DEST_LON)
            return miles, miles * settings.SHIPPING_RATE_PER_MILE, False
    
    # Try using the location field (city, state) if available
    if hasattr(listing, 'location') and listing.location:
        coords = await geocode_location(listing.location)
        if coords:
            lat, lon = coords
            miles = haversine_miles(lat, lon, settings.DEST_LAT, settings.DEST_LON)
            return miles, miles * settings.SHIPPING_RATE_PER_MILE, False
    
    # Try using phone number area code if available
    if hasattr(listing, 'phone') and listing.phone:
        area_code = extract_area_code_from_phone(listing.phone)
        if area_code:
            coords = await geocode_area_code(area_code)
            if coords:
                lat, lon = coords
                miles = haversine_miles(lat, lon, settings.DEST_LAT, settings.DEST_LON)
                return miles, miles * settings.SHIPPING_RATE_PER_MILE, False
    
    # Check raw data for phone number if not in phone field
    if hasattr(listing, 'raw') and listing.raw and isinstance(listing.raw, dict):
        owner_phone = listing.raw.get('ownerPhone')
        if owner_phone:
            area_code = extract_area_code_from_phone(str(owner_phone))
            if area_code:
                coords = await geocode_area_code(area_code)
                if coords:
                    lat, lon = coords
                    miles = haversine_miles(lat, lon, settings.DEST_LAT, settings.DEST_LON)
                    return miles, miles * settings.SHIPPING_RATE_PER_MILE, False
    
    # No coordinates, zip code, location, or phone available
    return 0.0, 0.0, True

async def score_listing_async(listing: Listing, appraisal: Optional[Appraisal]) -> Dict[str, Any]:
    if appraisal is None:
        return {
            "shipping_miles": 0.0,
            "shipping_cost": 0,
            "recon_cost": 0,
            "pack_cost": 0,
            "total_cost": listing.price,
            "gross_margin_dollars": 0,
            "margin_percent": 0.0,
            "category": "UNKNOWN",
            "explanations": {"reason": "no appraisal match"}
        }

    ship_miles, ship_cost_val, ship_unknown = await shipping_cost(listing)
    recon = recon_cost(listing.year, listing.mileage)
    pack = pack_cost(listing.price)
    mileage_adjustment = calculate_mileage_adjustment(listing, appraisal)

    # Apply mileage adjustment to the benchmark price (not cost)
    adjusted_benchmark = appraisal.benchmark_price + mileage_adjustment
    total_cost = listing.price + int(ship_cost_val) + recon + pack
    margin_dollars = adjusted_benchmark - total_cost
    margin_percent = (margin_dollars / total_cost) if total_cost > 0 else 0.0

    # Use the 3-category system: PROFITABLE (6%+), MAYBE (3-6%), UNKNOWN (<3%)
    if margin_percent >= 0.06:  # 6% or higher
        category = "PROFITABLE"
    elif margin_percent >= 0.03:  # 3-6%
        category = "MAYBE"
    else:  # Under 3% (including negative)
        category = "UNKNOWN"

    explanations = {
        "shipping": {"miles": round(ship_miles,2), "rate": settings.SHIPPING_RATE_PER_MILE, "cost": round(ship_cost_val,2), "unknown": ship_unknown},
        "recon": recon,
        "pack": pack,
        "mileage": {
            "listing_mileage": listing.mileage,
            "benchmark_mileage": getattr(appraisal, 'avg_mileage', None),
            "mileage_diff": listing.mileage - getattr(appraisal, 'avg_mileage', 0) if listing.mileage and getattr(appraisal, 'avg_mileage', None) else 0,
            "vehicle_category": categorize_vehicle(listing),
            "adjustment": mileage_adjustment
        },
        "totals": {
            "total_cost": total_cost, 
            "original_benchmark": appraisal.benchmark_price,
            "adjusted_benchmark": adjusted_benchmark,
            "margin_dollars": margin_dollars, 
            "margin_percent": round(margin_percent,4)
        },
        "thresholds": {"maybe_min_pct": settings.MAYBE_MIN_PCT, "profit_min_pct": settings.PROFIT_MIN_PCT}
    }

    return {
        "shipping_miles": ship_miles,
        "shipping_cost": int(ship_cost_val),
        "recon_cost": recon,
        "pack_cost": pack,
        "total_cost": total_cost,
        "gross_margin_dollars": margin_dollars,
        "margin_percent": margin_percent,
        "category": category,
        "explanations": explanations
    }

def score_listing(listing: Listing, appraisal: Optional[Appraisal]) -> Dict[str, Any]:
    """
    Synchronous wrapper for async score_listing function.
    This maintains backward compatibility with existing code.
    """
    import asyncio
    try:
        # Check if we're already in an event loop
        loop = asyncio.get_running_loop()
        # If we are, we need to handle this differently
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, score_listing_async(listing, appraisal))
            return future.result()
    except RuntimeError:
        # No event loop running, safe to use asyncio.run
        return asyncio.run(score_listing_async(listing, appraisal))