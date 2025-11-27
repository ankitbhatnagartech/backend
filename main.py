from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager
import logging
import json
from datetime import datetime

from schemas import TrafficInput, ArchitectureType, EstimationResult
from estimation_service import EstimationService
from pricing_service import PricingService
from database import Database
from pricing_fetcher import PricingFetcher

# Setup structured JSON logging
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

# Configure root logger
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.root.addHandler(handler)
logging.root.setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# Scheduler setup
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up ArchCost API...")
    
    # Connect to Database
    Database.connect()
    
    # Load existing dynamic prices
    await PricingService.load_dynamic_prices()
    
    # Start scheduler
    scheduler.add_job(PricingFetcher.fetch_latest_prices, 'cron', hour=0, minute=0) # Run at midnight
    scheduler.start()
    logger.info("Scheduler started. Price fetch job scheduled for 00:00 daily.")
    
    yield
    
    # Shutdown
    scheduler.shutdown()
    Database.close()
    logger.info("Scheduler and Database connection shut down.")

app = FastAPI(title="ArchCost API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Welcome to ArchCost API"}

@app.get("/health")
async def health_check():
    """Health check endpoint for container health monitoring"""
    try:
        # Check database connection
        db = Database.get_db()
        if db is None:
            return {"status": "unhealthy", "reason": "Database not connected"}, 503
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "0.1.0"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "reason": str(e)}, 503

@app.post("/estimate", response_model=EstimationResult)
async def estimate_cost(
    architecture: ArchitectureType = Body(...),
    traffic: TrafficInput = Body(...),
    currency: str = "USD"
):
    return EstimationService.estimate(architecture, traffic, currency)

@app.post("/admin/refresh-prices")
async def refresh_prices():
    """Manually trigger price fetch"""
    success = await PricingFetcher.fetch_latest_prices()
    if success:
        await PricingService.load_dynamic_prices() # Reload the new data
        return {"status": "success", "message": "Prices updated successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to fetch prices")

