from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
import pandas as pd
import upstox_client
from app.config import settings, logger
from app.models import OptionChainInput, MarketDepthInput
from app.utils.upstox_helpers import fetch_expiry, fetch_option_chain_raw, get_market_depth, get_upstox_config
from app.utils.data_processing import process_chain_data, calculate_metrics_data
from app.utils.volatility_calcs import compute_realized_vol

router = APIRouter()

@router.post("/option-chain", summary="Fetches and processes live option chain data")
async def get_option_chain_endpoint(data: OptionChainInput):
    """
    Fetches and processes live option chain data for a given instrument.
    Calculates key metrics like PCR, Max Pain, ATM IV, and Realized Volatility.
    """
    # Initialize Upstox API client for this specific request
    config = get_upstox_config(data.access_token)
    api_client = upstox_client.ApiClient(config)
    options_api = upstox_client.OptionsApi(api_client)

    try:
        expiry = fetch_expiry(options_api, data.instrument_key)
        if not expiry:
            logger.error("Failed to retrieve nearest expiry date.")
            raise HTTPException(status_code=500, detail="Failed to retrieve nearest expiry date.")

        chain = fetch_option_chain_raw(options_api, data.instrument_key, expiry)
        if not chain:
            logger.error("Failed to retrieve option chain data.")
            raise HTTPException(status_code=500, detail="Failed to retrieve option chain data.")

        # Extract spot price from the raw chain data
        spot = chain[0].get("underlying_spot_price")
        if not spot:
            logger.error("Failed to retrieve spot price from option chain.")
            raise HTTPException(status_code=500, detail="Failed to retrieve spot price.")

        df_processed, ce_oi, pe_oi = process_chain_data(chain)
        if df_processed.empty:
            logger.error("Processed option chain DataFrame is empty.")
            raise HTTPException(status_code=500, detail="Processed option chain DataFrame is empty.")

        pcr, max_pain, straddle_price, atm_strike, atm_iv = calculate_metrics_data(df_processed, ce_oi, pe_oi, spot)

        # Get instrument tokens for ATM CE and PE for depth fetching
        ce_token_row = df_processed[(df_processed['Strike'] == atm_strike) & (df_processed['CE_Token'] != '')]
        pe_token_row = df_processed[(df_processed['Strike'] == atm_strike) & (df_processed['PE_Token'] != '')]

        ce_token = ce_token_row['CE_Token'].values[0] if not ce_token_row.empty else None
        pe_token = pe_token_row['PE_Token'].values[0] if not pe_token_row.empty else None

        ce_depth = {"bid_volume": 0, "ask_volume": 0}
        if ce_token:
            try:
                ce_depth = get_market_depth(data.access_token, ce_token)
            except Exception as e:
                logger.warning(f"Could not fetch CE depth for {ce_token}: {e}")

        pe_depth = {"bid_volume": 0, "ask_volume": 0}
        if pe_token:
            try:
                pe_depth = get_market_depth(data.access_token, pe_token)
            except Exception as e:
                logger.warning(f"Could not fetch PE depth for {pe_token}: {e}")

        realized_vol = compute_realized_vol()

        response_data = {
            "nifty_spot": spot,
            "atm_strike": atm_strike,
            "straddle_price": straddle_price,
            "pcr": round(pcr, 2),
            "max_pain": max_pain,
            "expiry": expiry,
            "iv_skew_data": df_processed.to_dict(orient='records'), # Full DF might be large but required for strategy
            "ce_depth": ce_depth,
            "pe_depth": pe_depth,
            "atm_iv": round(atm_iv, 2),
            "realized_volatility": realized_vol,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data": chain # Raw chain data for strategy execution
        }
        logger.info("Successfully fetched and processed market data via /option-chain.")
        return response_data

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.exception("An unexpected error occurred in /option-chain endpoint.")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

@router.post("/market-depth", summary="Fetches market depth for a given instrument token")
async def get_market_depth_endpoint(data: MarketDepthInput):
    """
    Fetches market depth (total bid/ask quantity) for a specified instrument token.
    """
    try:
        depth = get_market_depth(data.access_token, data.instrument_key)
        return depth
    except Exception as e:
        logger.error(f"Market depth error: {e}")
        raise HTTPException(status_code=500, detail=f"Market depth error: {str(e)}")
