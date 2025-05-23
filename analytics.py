from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.config import logger
from app.models import TradeInput, RegimeInput, RiskCheckInput, Trade
from app.dependencies import get_db
from app.utils.risk_management import calculate_discipline_score

router = APIRouter()

@router.post("/log/trade", summary="Logs a trade into the database")
def log_trade(trade: TradeInput, db: Session = Depends(get_db)):
    """
    Logs a completed trade into the SQLite database, recording details
    like strategy, entry/exit prices, P&L, and market regime score.
    """
    try:
        new_trade = Trade(**trade.model_dump())
        db.add(new_trade)
        db.commit()
        db.refresh(new_trade)
        return {"status": "success", "trade_id": new_trade.id}
    except Exception as e:
        logger.error(f"Trade logging error: {e}")
        raise HTTPException(status_code=500, detail=f"Trade logging error: {str(e)}")

@router.get("/analytics/performance", summary="Retrieves overall trading performance analytics")
def get_performance_analytics(db: Session = Depends(get_db)):
    """
    Provides aggregated performance statistics from all logged trades,
    including total trades, total P&L, average regime score, and win/loss counts.
    """
    try:
        trades = db.query(Trade).all()
        total = len(trades)
        if total == 0:
            return {
                "total_trades": 0,
                "total_pnl": 0.0,
                "avg_regime_score": 0.0,
                "winning_trades": 0,
                "losing_trades": 0
            }
        total_pnl = sum(t.pnl for t in trades)
        avg_regime = sum(t.regime_score for t in trades) / total
        winning_trades = sum(1 for t in trades if t.pnl > 0)
        losing_trades = sum(1 for t in trades if t.pnl < 0)
        return {
            "total_trades": total,
            "total_pnl": round(total_pnl, 2),
            "avg_regime_score": round(avg_regime, 2),
            "winning_trades": winning_trades,
            "losing_trades": losing_trades
        }
    except Exception as e:
        logger.error(f"Performance analytics error: {e}")
        raise HTTPException(status_code=500, detail=f"Performance analytics error: {str(e)}")

@router.post("/risk/check", summary="Performs real-time risk checks based on defined parameters")
def check_risk(data: RiskCheckInput):
    """
    Evaluates a potential trade against predefined risk parameters such as
    max loss allowed, estimated loss, daily P&L, and daily loss limits.
    Returns "ALLOW" or "BLOCK" with alerts.
    """
    try:
        alerts = []
        vol_factor = 1.0 + (data.iv_rv_ratio - 1) * 0.5 if data.iv_rv_ratio > 1 else 1.0
        adjusted_loss = data.estimated_loss * vol_factor
        if adjusted_loss > data.max_loss_allowed:
            alerts.append(f"Max loss exceeded: Projected loss {adjusted_loss:.2f} > Allowed {data.max_loss_allowed:.2f}")

        potential_daily_pnl = data.daily_pnl - adjusted_loss
        if potential_daily_pnl < -abs(data.max_daily_limit):
            alerts.append(f"Daily loss limit breached: Current + Projected P&L {potential_daily_pnl:.2f} < Daily limit -{data.max_daily_limit:.2f}")

        return {"status": "BLOCK" if alerts else "ALLOW", "alerts": alerts}
    except Exception as e:
        logger.error(f"Risk check error: {e}")
        raise HTTPException(status_code=500, detail=f"Risk check error: {str(e)}")

@router.post("/regime/score", summary="Calculates a market regime score based on various indicators")
def get_regime_score(data: RegimeInput):
    """
    Calculates a composite market regime score based on indicators like IVP, PCR, VIX,
    FII/DII net positioning, event impact, realized volatility, and IV skew slope.
    Classifies the market into categories (e.g., High Volatility, Range-Bound).
    """
    try:
        score = 0
        explanation = []

        if data.ivp > 70:
            score += 3
            explanation.append("Very high IVP (>70%) indicates high option premiums.")
        elif data.ivp > 50:
            score += 2
            explanation.append("High IVP (>50%) indicates elevated option premiums.")

        if data.vix > 20:
            score += 3
            explanation.append("High VIX (>20) suggests significant market fear.")
        elif data.vix > 14:
            score += 2
            explanation.append("Elevated VIX (>14) indicates increased volatility expectations.")

        if data.pcr > 1.5:
            score += 2
            explanation.append(f"Very bullish PCR ({data.pcr}).")
        elif data.pcr < 0.7:
            score += 2
            explanation.append(f"Very bearish PCR ({data.pcr}).")
        elif 0.9 <= data.pcr <= 1.1:
            score += 1
            explanation.append(f"Neutral PCR ({data.pcr}).")

        if data.fii_net > 2000:
            score += 2
            explanation.append("Strong FII net long positioning (>2000 Cr).")
        elif data.fii_net < -1000:
            score += 2
            explanation.append("Strong FII net short positioning (<-1000 Cr).")

        if data.event_impact > 0.7:
            score += 3
            explanation.append("High event impact score (>0.7) indicates significant potential market moves.")
        elif data.event_impact > 0.4:
            score += 1
            explanation.append("Moderate event impact score (>0.4).")

        if data.realized_vol > 20:
            score += 3
            explanation.append("Very high realized volatility (>20%) indicates sharp price swings.")
        elif data.realized_vol > 15:
            score += 1
            explanation.append("High realized volatility (>15%).")

        if data.iv_skew_slope > 0.7:
            score += 2
            explanation.append("Steep IV skew slope (>0.7) suggests bearish sentiment (puts are expensive).")
        elif data.iv_skew_slope < -0.3:
            score += 1
            explanation.append("Negative IV skew slope (<-0.3) suggests bullish sentiment (calls are expensive).")

        regime = "Uncertain/Volatile"
        if score >= 10:
            regime = "High Volatility / Event Driven"
        elif score >= 6:
            regime = "Trend-Following / Moderate Volatility"
        elif score < 3:
            regime = "Low Volatility / Range-Bound"

        return {
            "regime_score": score,
            "regime": regime,
            "explanation": explanation
        }
    except Exception as e:
        logger.error(f"Regime score error: {e}")
        raise HTTPException(status_code=500, detail=f"Regime score error: {str(e)}")

@router.get("/discipline/score", summary="Retrieves the trading discipline score")
def get_discipline_score_endpoint(db: Session = Depends(get_db)):
    """
    Calculates and returns a trading discipline score based on historical trades,
    identifying potential violations like excessive high-risk trades or overtrading.
    """
    try:
        trades = db.query(Trade).all()
        result = calculate_discipline_score(trades)
        return result
    except Exception as e:
        logger.error(f"Discipline score endpoint error: {e}")
        raise HTTPException(status_code=500, detail=f"Discipline score endpoint error: {str(e)}")
