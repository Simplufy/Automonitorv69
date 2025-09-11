from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db import Base

class Appraisal(Base):
    __tablename__ = "appraisals"
    id = Column(Integer, primary_key=True)
    year = Column(Integer, index=True)
    make = Column(String(100), index=True)
    model = Column(String(100), index=True)
    trim = Column(String(100), nullable=True, index=True)
    benchmark_price = Column(Integer, nullable=False)
    avg_mileage = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Listing(Base):
    __tablename__ = "listings"
    id = Column(Integer, primary_key=True)
    vin = Column(String(32), unique=True, nullable=False)
    year = Column(Integer, index=True)
    make = Column(String(100), index=True)
    model = Column(String(100), index=True)
    trim = Column(String(100), nullable=True, index=True)
    price = Column(Integer, nullable=False)
    mileage = Column(Integer, nullable=True)
    location = Column(String(200), nullable=True)
    seller_type = Column(String(50), nullable=True)
    seller = Column(String(200), nullable=True)
    url = Column(String(500), nullable=False)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    zip = Column(String(10), nullable=True)
    source = Column(String(100), nullable=False, default="apify_autotrader")
    raw = Column(JSON, nullable=True)
    ingested_at = Column(DateTime, default=datetime.utcnow)

class MatchResult(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"))
    appraisal_id = Column(Integer, ForeignKey("appraisals.id", ondelete="SET NULL"), nullable=True)
    match_level = Column(String(8), nullable=False)  # YMMT, YMM, NONE
    match_confidence = Column(Integer, nullable=False, default=0)
    shipping_miles = Column(Float, nullable=True)
    shipping_cost = Column(Integer, nullable=True)
    recon_cost = Column(Integer, nullable=True)
    pack_cost = Column(Integer, nullable=True)
    total_cost = Column(Integer, nullable=True)
    gross_margin_dollars = Column(Integer, nullable=True)
    margin_percent = Column(Float, nullable=True)
    category = Column(String(12), nullable=False, default="SKIP")
    explanations = Column(JSON, nullable=True)
    scored_at = Column(DateTime, default=datetime.utcnow)

    listing = relationship("Listing")
    appraisal = relationship("Appraisal")
