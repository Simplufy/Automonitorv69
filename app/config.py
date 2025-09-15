from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://localhost/autoprofit"
    ADMIN_PASSPHRASE: str = "CHANGE_ME_IMMEDIATELY"

    APIFY_TOKEN: str | None = None
    # Cars.com actor ID
    APIFY_CARSCOM_ACTOR_ID: str | None = None
    ENABLE_APIFY_POLLING: bool = False
    APIFY_POLL_INTERVAL_MINUTES: int = 60

    DEST_LAT: float = 40.117802
    DEST_LON: float = -83.135870
    SHIPPING_RATE_PER_MILE: float = 0.80

    RECON_NEW_MILES_MAX: int = 5000
    RECON_NEW_COST: int = 800
    RECON_OLD_YEAR_THRESHOLD: int = 2012
    RECON_OLD_COST: int = 1300
    RECON_STANDARD_COST: int = 3000

    PACK_TIERS: list[dict] = Field(default_factory=lambda: [
        {"min": 0, "max": 19999, "cost": 500},
        {"min": 20000, "max": 39999, "cost": 800},
        {"min": 40000, "max": 59999, "cost": 1200},
        {"min": 60000, "max": 79999, "cost": 1500},
        {"min": 80000, "max": 119999, "cost": 1800},
        {"min": 120000, "max": 149999, "cost": 2200},
        {"min": 150000, "max": 179999, "cost": 2800},
        {"min": 180000, "max": 219999, "cost": 3400},
        {"min": 220000, "max": 259999, "cost": 4000},
        {"min": 260000, "max": 299999, "cost": 5000},
        {"min": 300000, "max": 10**9, "cost": 7000},
    ])

    PROFIT_MIN_PCT: float = 0.07  # 7%
    MAYBE_MIN_PCT: float = 0.06   # 6%
    UNKNOWN_MIN_PCT: float = 0.05  # 5%

    # Mileage adjustment configuration
    MILEAGE_SUPERCAR_PRICE_THRESHOLD: int = 70000  # Over $70k = supercar/extreme lux
    MILEAGE_HIGH_MILE_THRESHOLD: int = 45000       # Over 45k miles threshold
    
    # Mileage adjustment amounts (negative = penalty, positive = bonus)
    MILEAGE_SUPERCAR_ADJUSTMENT_PER_5K: int = 3000     # ±$3,000 per 5,000 miles for supercars
    MILEAGE_HIGH_MILE_ADJUSTMENT_PER_5K: int = 2000    # -$2,000 per 5,000 miles for high-mile coupes/convertibles
    MILEAGE_SEDAN_ADJUSTMENT_PER_10K: int = 2000       # ±$2,000 per 10,000 miles for normal sedans
    MILEAGE_SUV_ADJUSTMENT_PER_10K: int = 1500         # ±$1,500 per 10,000 miles for SUVs

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()