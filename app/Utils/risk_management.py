from app.models import Trade
from app.config import logger
from fastapi import HTTPException
from sqlalchemy.orm import Session

def calculate_discipline_score(trades: list[Trade]):
    """Calculates a trading discipline score."""
    try:
        if not trades:
            return {"score": 100, "violations": []}
        violations = []
        total_trades = len(trades)
        high_risk_trades = sum(1 for t in trades if t.regime_score < 3) # Assuming a score < 3 is high risk
        daily_trades = {}
        for t in trades:
            date = t.timestamp.date()
            daily_trades[date] = daily_trades.get(date, 0) + 1
        overtrading_days = sum(1 for count in daily_trades.values() if count > 3) # More than 3 trades a day is overtrading
        losing_trades = sum(1 for t in trades if t.pnl < 0)
        score = 100
        if high_risk_trades / total_trades > 0.2:
            violations.append("Too many high-risk trades (low regime score)")
            score -= 20
        if overtrading_days:
            violations.append(f"Overtrading on {overtrading_days} days (>3 trades/day)")
            score -= 10 * overtrading_days
        if losing_trades / total_trades > 0.5:
            violations.append("More than 50% trades are losing")
            score -= 20
        score = max(0, score)
        return {"score": score, "violations": violations}
    except Exception as e:
        logger.error(f"Discipline score calculation error: {e}")
        raise HTTPException(status_code=500, detail=f"Discipline score calculation error: {str(e)}")
