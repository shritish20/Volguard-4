from fastapi import APIRouter, HTTPException
from datetime import datetime
import pandas as pd
import upstox_client
from app.config import settings, logger
from app.models import OptionChainInput
from app.utils.upstox_helpers import fetch_expiry, fetch_option_chain_raw, get_upstox_config
from app.utils.data_processing import process_chain_data, calculate_metrics_data
from app.utils.volatility_calcs import compute_realized_vol

router = APIRouter()

@router.post("/option-chain", summary="Fetches and processes live option chain data")
async def get_option_chain_endpoint(data: OptionChainInput):
    config = get_upstox_config(data.access_token)
    api_client = upstox_client.ApiClient(config)
    option_chain_api = upstox_client.OptionChainApi(api_client)

    try:
        expiry = await fetch_expiry(option_chain_api, data.instrument_key)
        if not expiry:
            logger.error("Failed to retrieve nearest expiry date.")
            raise HTTPException(status_code=500, detail="Failed to retrieve nearest expiry date.")

        chain = await fetch_option_chain_raw(option_chain_api, data.instrument_key, expiry)
        if not chain:
            logger.error("Failed to retrieve option chain data.")
            raise HTTPException(status_code=500, detail="Failed to retrieve option chain data.")

        spot = chain[0].get("underlying_spot_price") if chain else None
        if not spot:
            logger.error("Failed to retrieve spot price from option chain.")
            raise HTTPException(status_code=500, detail="Failed to retrieve spot price.")

        df_processed, ce_oi, pe_oi = process_chain_data(chain)
        if df_processed.empty:
            logger.error("Processed option chain DataFrame is empty.")
            raise HTTPException(status_code=500, detail="Processed option chain DataFrame is empty.")

        pcr, max_pain, straddle_price, atm_strike, atm_iv = calculate_metrics_data(df_processed, ce_oi, pe_oi, spot)

        response_data = {
            "nifty_spot": spot,
            "atm_strike": atm_strike,
            "straddle_price": straddle_price,
            "pcr": round(pcr, 2),
            "max_pain": max_pain,
            "expiry": expiry,
            "iv_skew_data": df_processed.to_dict(orient='records'),
            "atm_iv": round(atm_iv, 2),
            "realized_volatility": compute_realized_vol(),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data": chain
        }
        logger.info("Successfully fetched and processed market data via /option-chain.")
        return response_data
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.exception("An unexpected error occurred in /option-chain endpoint.")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")
