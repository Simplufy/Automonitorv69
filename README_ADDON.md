
# Intelligent Parsing + Market Pricing Add-On

This fork of your app adds:
- **/api/ingest-freeform**: send raw listing titles; we parse Y/M/M/T with OpenAI.
- **Market pricing**: after the normal /api/ingest flow, we compute fair value & 30/60 day targets from your stored comps and attach them to MatchResult.explanations.market_pricing.
- **Profitability flag**: if list - predicted <= -DESIRED_MARGIN and (list - predicted)/predicted <= -REQUIRED_MARGIN_PCT (default 3%)

## Setup (Replit)
1. Add Secret: `OPENAI_API_KEY`
2. (Optional) Add `DESIRED_MARGIN` (default 700).
3. `pip install -r requirements.txt`
4. `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`

## Sending data
- Existing endpoint (structured): `POST /api/ingest` with your current payload.
- New freeform endpoint: `POST /api/ingest-freeform` with
  ```json
  { "title": "2021 Audi RS7 Performance 4.0T quattro", "price": 87990, "mileage": 22150, "url": "https://...", "vin": "optional" }
  ```

Market outputs are placed in `match.explanations.market_pricing`.
