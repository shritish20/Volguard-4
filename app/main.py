from fastapi import FastAPI, HTTPException
from app.config import settings, logger
from app.database import create_db_and_tables
from app.routers import market_data, strategy, volatility, user_management, analytics, trade

app = FastAPI(
    title="VolGuard Pro Backend API",
    description="API for fetching market data, volatility forecasting, and trade execution.",
    version="1.0.0"
)

app.include_router(market_data.router, prefix="/market-data", tags=["Market Data"])
app.include_router(strategy.router, prefix="/strategy", tags=["Strategy & Backtesting"])
app.include_router(volatility.router, prefix="/volatility", tags=["Volatility"])
app.include_router(user_management.router, prefix="/user", tags=["User & Account"])
app.include_router(analytics.router, prefix="/analytics", tags=["Trade Analytics & Risk"])
app.include_router(trade.router, prefix="/trade", tags=["Trade Execution"])

@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI app starting up...")
    create_db_and_tables()
    logger.info("Database tables checked/created.")

@app.get("/", tags=["Root"])
def root():
    return {"status": "healthy", "message": "VolGuard Backend is running."}

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    logger.error(f"HTTP Exception: {exc.status_code} - {exc.detail}")
    return HTTPException(status_code=exc.status_code, detail=exc.detail)

@app.exception_handler(Exception)
async def generic_exception_handler(request, exc: Exception):
    logger.exception(f"Unhandled Exception: {exc}")
    return HTTPException(status_code=500, detail="Internal Server Error")
