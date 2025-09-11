from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routes.web_front import router as web_front_router
from app.routes.web_admin import router as web_admin_router
from app.routes.api_ingest import router as api_ingest_router
from app.routes.web_fetch import router as web_fetch_router
from app.jobs import init_scheduler

app = FastAPI(title="AutoProfit")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(web_front_router)
app.include_router(web_admin_router)
app.include_router(api_ingest_router)
app.include_router(web_fetch_router)

@app.on_event("startup")
async def startup_event():
    # Initialize database tables if they don't exist
    from app.db import engine
    from app.models import Base
    Base.metadata.create_all(bind=engine)
    init_scheduler(app)

@app.get("/")
def root():
    return {"status": "healthy", "service": "AutoProfit"}

@app.get("/healthz")
def healthz():
    return {"ok": True}