import pandas as pd
import numpy as np
import requests
from arch import arch_model
from app.config import settings, logger
import retrying
from fastapi import HTTPException

@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
def compute_realized_vol(nifty_df_path: str = settings.NIFTY_HISTORICAL_DATA_URL):
    """Computes 7-day realized volatility from historical Nifty data."""
    try:
        nifty_df = pd.read_csv(nifty_df_path)
        nifty_df.columns = nifty_df.columns.str.strip()
        nifty_df["Date"] = pd.to_datetime(nifty_df["Date"], format="%d-%b-%Y", errors="coerce")
        nifty_df = nifty_df.dropna(subset=["Date"]).set_index("Date")
        nifty_df = nifty_df.rename(columns={"Close": "NIFTY_Close"})
        if 'NIFTY_Close' not in nifty_df.columns:
            raise ValueError("CSV missing 'NIFTY_Close' column for realized volatility calculation.")
        nifty_df = nifty_df[["NIFTY_Close"]].dropna().sort_index()

        if nifty_df.empty or len(nifty_df) < 7:
            logger.warning("Not enough data to compute 7-day realized volatility. Returning 0.")
            return 0.0

        log_returns = np.log(nifty_df["NIFTY_Close"].pct_change() + 1).dropna()
        last_7d_log_returns = log_returns[-7:]

        if last_7d_log_returns.empty:
            return 0.0

        last_7d_std = last_7d_log_returns.std()
        realized_vol = last_7d_std * np.sqrt(252) * 100
        return realized_vol if not np.isnan(realized_vol) else 0.0
    except Exception as e:
        logger.error(f"Error computing realized volatility: {e}")
        return 0.0

def calculate_rolling_and_fixed_hv(df: pd.DataFrame, periods: list = [7, 30, 252]):
    """Calculates rolling and fixed historical volatility."""
    try:
        if 'Close' not in df.columns:
            raise ValueError("DataFrame must contain a 'Close' column for HV calculation.")

        results = {}
        returns = np.log(df['Close'] / df['Close'].shift(1)).dropna()

        for days in periods:
            if len(returns) < days:
                results[f"hv_{days}d"] = 0.0
                continue
            vol = returns.rolling(window=days).std() * np.sqrt(252) * 100
            results[f"hv_{days}d"] = round(vol.iloc[-1], 2) if not vol.empty else 0.0
        return results
    except Exception as e:
        logger.error(f"Historical volatility error: {e}")
        raise HTTPException(status_code=500, detail=f"Historical volatility calculation error: {str(e)}")

def predict_garch_model(nifty_df_path: str = settings.NIFTY_HISTORICAL_DATA_URL):
    """Predicts future volatility using a GARCH(1,1) model."""
    try:
        df = pd.read_csv(nifty_df_path)
        df.columns = df.columns.str.strip()
        if 'Date' not in df.columns:
            raise ValueError(f"CSV file does not contain 'Date' column. Available columns: {list(df.columns)}")
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce", format="%d-%b-%Y")
        df = df.dropna(subset=["Date"]).set_index("Date").sort_index()
        if 'Close' not in df.columns:
            raise ValueError(f"CSV file does not contain 'Close' column. Available columns: {list(df.columns)}")
        returns = np.log(df["Close"] / df["Close"].shift(1)).dropna() * 100

        if returns.empty or len(returns) < 10: # Ensure enough data for GARCH
            raise ValueError("Not enough historical data to fit GARCH model.")

        model = arch_model(returns, vol="Garch", p=1, q=1)
        result = model.fit(disp="off")
        forecast = result.forecast(horizon=7)
        vols = np.sqrt(forecast.variance.values[-1]) * np.sqrt(252)

        last_date = df.index[-1]
        future_dates = pd.bdate_range(start=last_date + pd.Timedelta(days=1), periods=7)

        return [{"date": str(d.date()), "forecast_volatility": round(v, 2)} for d, v in zip(future_dates, vols)]
    except Exception as e:
        logger.error(f"GARCH prediction error: {e}")
        raise HTTPException(status_code=500, detail=f"GARCH prediction error: {str(e)}")
