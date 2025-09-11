# AutoProfit (Replit-ready)

Lean FastAPI app: ingest Autotrader via Apify (polling), de-dupe by VIN, match YMMT→YMM to Appraisal DB, compute **% margin after costs** (shipping + recon + pack).

## Quick start
```bash
pip install -r requirements.txt
make db-init
make seed
make dev
```
Add Replit Secrets: `APIFY_TOKEN`, `APIFY_ACTOR_ID`, `ADMIN_PASSPHRASE`.

## Business rules
- Dest: 43065 (Powell, OH) → (40.1573, -83.0752)
- Shipping: $0.80/mile (Haversine; if no coords → 0 + flag)
- Recon:
  - mileage ≤ 5,000 → $800
  - else if year ≥ 2012 → $1,300
  - else → $3,000
- Pack by price: 0–19,999:500; 20–39,999:800; 40–59,999:1200; 60–79,999:1500; 80–119,999:1800; 120–149,999:2200; 150–179,999:2800; 180–219,999:3400; 220–259,999:4000; 260–299,999:5000; 300k+:7000
- Categorize by **percent margin after costs**:
  - PROFITABLE ≥ 7%, MAYBE 6–7%, else SKIP

## Admin
- `/admin` login → upload CSV (bulk replace), edit Settings, Manual Fetch.
- CSV: `year,make,model,trim,benchmark_price,avg_mileage,notes`
