from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base
from typing import Optional, List, Dict

Base = declarative_base()

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True)
    strategy = Column(String)
    entry_price = Column(Float)
    exit_price = Column(Float)
    pnl = Column(Float)
    regime_score = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

class XGBInput(BaseModel):
    ATM_IV: float
    Realized_Vol: float
    IVP: float
    Event_Impact_Score: float
    FII_DII_Net_Long: float
    PCR: float
    VIX: float

class TradeInput(BaseModel):
    strategy: str
    entry_price: float
    exit_price: float
    pnl: float
    regime_score: float

class StrategyInput(BaseModel):
    ivp: float
    vix: float
    pcr: float
    straddle_price: float
    event_impact_score: float
    atm_iv: float
    realized_vol: float
    iv_skew_slope: float

class RiskCheckInput(BaseModel):
    strategy: str
    max_loss_allowed: float
    estimated_loss: float
    daily_pnl: float
    max_daily_limit: float
    iv_rv_ratio: float

class RegimeInput(BaseModel):
    ivp: float
    pcr: float
    vix: float
    fii_net: float
    event_impact: float
    realized_vol: float
    iv_skew_slope: float

class OptionChainInput(BaseModel):
    access_token: str
    instrument_key: str = "NSE_INDEX|Nifty 50"

class StrategyExecuteInput(BaseModel):
    access_token: str
    strategy_name: str
    spot_price: float
    quantity: int
    otm_distance: float
    option_chain: Dict

class UserDetailsInput(BaseModel):
    access_token: str

class VolatilityHistoricalInput(BaseModel):
    period: str = "all"

class BacktestInput(BaseModel):
    strategy_name: str
    quantity: int
    period: int

class OrderLeg(BaseModel):
    instrument_key: str
    quantity: int
    action: str
    price: Optional[float] = 0.0
    trigger_price: Optional[float] = 0.0
    disclosed_quantity: Optional[int] = 0
    tag: Optional[str] = "volguard"

class TradePnlRequest(BaseModel):
    access_token: str
    order_id: str
