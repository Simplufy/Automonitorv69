from pydantic import BaseModel
from typing import Optional, Any

class ListingIn(BaseModel):
    vin: str
    year: int
    make: str
    model: str
    trim: Optional[str] = None
    price: int
    mileage: Optional[int] = None
    url: str
    seller: Optional[str] = None
    seller_type: Optional[str] = None
    location: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    zip: Optional[str] = None
    source: str = "apify_autotrader"
    raw: Optional[Any] = None