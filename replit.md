# AutoProfit

## Overview
AutoProfit is a FastAPI-based automotive arbitrage analysis platform that automates the process of finding profitable car deals. The system ingests vehicle listings from Autotrader via Apify scraping, matches them against an appraisal database, and calculates profit margins after accounting for shipping, reconditioning, and packaging costs. The application categorizes deals as PROFITABLE (≥7% margin), MAYBE (6-7% margin), or UNKNOWN (<6% margin) to help dealers identify the most lucrative opportunities.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Architecture
- **Framework**: FastAPI with async/await support for high-performance API endpoints
- **Database**: SQLite with SQLAlchemy ORM for data persistence and Alembic for migrations
- **Data Models**: Three core entities - Listings (scraped vehicles), Appraisals (benchmark pricing), and MatchResults (calculated profits)
- **Scheduled Jobs**: APScheduler handles periodic Apify polling for new listings every 60 minutes

### Frontend Architecture  
- **Template Engine**: Jinja2 templates with HTMX for dynamic content updates without full page reloads
- **Admin Interface**: Password-protected admin panel for CSV uploads, manual data fetching, and configuration management
- **Dashboard**: Real-time categorized listing views with profit calculations and filtering capabilities

### Business Logic Components
- **Matching Service**: Fuzzy string matching using RapidFuzz to match vehicle listings to appraisal benchmarks (YMMT exact → YMM exact → fuzzy fallback)
- **Scoring Service**: Calculates total costs including distance-based shipping (Haversine formula), mileage/year-based reconditioning, and price-tiered packaging costs
- **Geocoding Service**: Converts zip codes to coordinates using Zippopotam.us API for accurate shipping distance calculations

### Data Processing Pipeline
- **Ingestion**: Apify actor scrapes Autotrader listings and normalizes data structure
- **Deduplication**: VIN-based deduplication prevents duplicate processing
- **Enrichment**: Geographic coordinates resolution and cost calculations
- **Categorization**: Automated profit margin categorization based on configurable thresholds

## External Dependencies

### Third-Party APIs
- **Apify Platform**: Vehicle listing scraping via configurable actor ID with token-based authentication
- **Zippopotam.us API**: Free geocoding service for zip code to coordinate conversion (no API key required)

### Python Libraries
- **FastAPI Stack**: uvicorn, pydantic, python-multipart for web framework and validation
- **Database**: SQLAlchemy, Alembic for ORM and migrations
- **HTTP Client**: httpx for async API calls to external services
- **Scheduling**: APScheduler for background job management
- **Fuzzy Matching**: RapidFuzz for intelligent vehicle matching
- **Templates**: Jinja2 for server-side rendering

### Configuration Management
- **Environment Variables**: Pydantic Settings for type-safe configuration with .env file support
- **Required Secrets**: APIFY_TOKEN, APIFY_ACTOR_ID, ADMIN_PASSPHRASE for Replit Secrets integration
- **Business Rules**: Configurable cost tiers, profit thresholds, and geographic parameters

### Database Schema
- **Single File Storage**: SQLite database with foreign key constraints and cascading deletes
- **Indexing Strategy**: Composite indexes on year/make/model for efficient matching queries
- **JSON Storage**: Raw scraped data preserved in JSON columns for audit trails and debugging