from fastapi import APIRouter, HTTPException
import pandas as pd
import numpy as np
import requests
import pickle
from app.config import settings, logger
from app.models import XGBInput, VolatilityHistoricalInput
from app.utils.volatility_calcs import predict_garch_model, calculate_rolling_and_fixed_hv

router = APIRouter()

@router.post("/predict/xgboost", summary="Predicts volatility using an XGBoost model")
def predict_vol_xgboost(data: XGBInput):
    """
    Predicts future volatility (e.g., 7-day realized volatility) using a pre-trained XGBoost model.
    Input features include ATM IV, Realized Vol, IVP, Event Impact Score, FII/DII Net Long, PCR, and VIX.
    """
    try:
        response = requests.get(settings.XGBOOST_MODEL_URL)
        response.raise_for_status()
        xgb_model = pickle.loads(response.content)
        df = pd.DataFrame([data.model_dump()])
        pred = xgb_model.predict(df)
        return {"predicted_volatility_7d (%)": round(float(pred[0]), 2)}
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download XGBoost model: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to download XGBoost model: {e}")
    except Exception as e:
        logger.error(f"XGBoost prediction error: {e}")
        raise HTTPException(status_code=500, detail=f"XGBoost prediction error: {str(e)}")

@router.get("/predict/garch", summary="Predicts future volatility using a GARCH(1,1) model")
def predict_vol_garch():
    """
    Predicts future volatility for the next 7 business days using a GARCH(1,1) model
    fitted on historical Nifty 50 returns.
    """
    try:
        forecast_results = predict_garch_model(settings.NIFTY_HISTORICAL_DATA_URL)
        return {"7_day_garch_forecast": forecast_results}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"GARCH prediction endpoint error: {e}")
        raise HTTPException(status_code=500, detail=f"GARCH prediction endpoint error: {str(e)}")

@router.get("/volatility/historical", summary="Computes and returns historical volatility for Nifty 50")
def get_historical_volatility(period: str = "all"):
    """
    Computes and returns historical volatility for Nifty 50 for specified periods.
    Query parameter `period` can be "7d", "30d", "1y", or "all".
    """
    try:
        df = pd.read_csv(settings.NIFTY_HISTORICAL_DATA_URL)
        df.columns = df.columns.str.strip()
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce", format="%d-%b-%Y")
        df = df.dropna(subset=["Date"]).set_index("Date").sort_index()
        if 'Close' not in df.columns:
            raise ValueError(f"CSV file does not contain 'Close' column")

        periods_map = {"7d": 7, "30d": 30, "1y": 252}

        results = {}
        if period == "all":
            for p_str, days in periods_map.items():
                temp_results = calculate_rolling_and_fixed_hv(df, periods=[days])
                results.update({f"hv_{p_str}": temp_results[f"hv_{days}d"]})
        else:
            days = periods_map.get(period)
            if not days:
                raise HTTPException(status_code=400, detail="Invalid period. Choose from '7d', '30d', '1y', 'all'.")
            temp_results = calculate_rolling_and_fixed_hv(df, periods=[days])
            results.update({f"hv_{period}": temp_results[f"hv_{days}d"]})

        return results
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Historical volatility endpoint error: {e}")
        raise HTTPException(status_code=500, detail=f"Historical volatility endpoint error: {str(e)}")
