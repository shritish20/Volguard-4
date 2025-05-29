import requests
import asyncio
from fastapi import HTTPException
from typing import Optional, List, Dict
from tenacity import retry, stop_after_attempt, wait_fixed
from app.config import settings, logger
import traceback

def get_upstox_config(access_token: str) -> dict:
    logger.debug(f"Creating Upstox config with token: {access_token[:4]}...")
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    base_url = settings.UPSTOX_BASE_URL
    logger.debug(f"Upstox base URL: {base_url}")
    return {"base_url": base_url, "headers": headers}

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def fetch_expiry(config: dict, instrument_key: str) -> Optional[str]:
    logger.debug(f"Fetching expiry for {instrument_key}")
    try:
        url = f"{config['base_url']}/option/contract"
        params = {'instrument_key': instrument_key}
        logger.debug(f"API Request: URL={url}, Headers={config['headers']}, Params={params}")
        response = requests.get(url, headers=config['headers'], params=params)
        logger.debug(f"API Response: Status={response.status_code}, Body={response.text}")
        response.raise_for_status()
        contracts = response.json().get("data", [])
        if not contracts:
            logger.error(f"No contracts returned for {instrument_key}")
            return None
        expiry_dates = sorted(set(contract['expiry'] for contract in contracts))
        return expiry_dates[0] if expiry_dates else None
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch expiry: {str(e)}, Status={e.response.status_code if e.response else 500}, Body={e.response.text if e.response else ''}, Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error fetching expiry: {str(e)}, Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def fetch_option_chain_raw(config: dict, instrument_key: str, expiry_date: str) -> List[Dict]:
    logger.debug(f"Fetching option chain for {instrument_key}, expiry: {expiry_date}")
    try:
        url = f"{config['base_url']}/option/chain"
        params = {'instrument_key': instrument_key, 'expiry_date': expiry_date}
        logger.debug(f"API Request: URL={url}, Headers={config['headers']}, Params={params}")
        response = requests.get(url, headers=config['headers'], params=params)
        logger.debug(f"API Response: Status={response.status_code}, Body={response.text}")
        response.raise_for_status()
        data = response.json().get('data', [])
        if not data:
            logger.error(f"Empty option chain data for {instrument_key}, expiry: {expiry_date}")
        return data
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch option chain: {str(e)}, Status={e.response.status_code if e.response else 500}, Body={e.response.text if e.response else ''}, Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error fetching option chain: {str(e)}, Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def place_order_for_leg(config: dict, leg: dict) -> dict:
    logger.debug(f"Placing order: {leg}")
    try:
        funds = await get_funds_and_margin(config)
        if funds.get("equity", {}).get("available_margin", 0) < leg.get("margin_required", float('inf')):
            logger.error("Insufficient funds for order")
            raise HTTPException(status_code=400, detail="Insufficient funds")

        url = f"{config['base_url']}/order/place"
        payload = {
            "instrument_key": leg["instrument_key"],
            "quantity": leg["quantity"],
            "product": "D",
            "order_type": leg.get("order_type", "MARKET"),
            "transaction_type": leg["action"],
            "price": leg.get("price", 0),
            "trigger_price": leg.get("trigger_price", 0),
            "disclosed_quantity": leg.get("disclosed_quantity", 0),
            "validity": "DAY",
            "tag": leg.get("tag", "volguard")
        }
        logger.debug(f"Order Request: URL={url}, Payload={payload}")
        response = requests.post(url, headers=config['headers'], json=payload)
        logger.debug(f"Order Response: Status={response.status_code}, Body={response.text}")
        response.raise_for_status()
        return response.json().get("data", {})
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to place order: {str(e)}, Status={e.response.status_code if e.response else 500}, Body={e.response.text if e.response else ''}, Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error placing order: {str(e)}, Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def get_funds_and_margin(config: dict) -> dict:
    from datetime import datetime, time
    current_time = datetime.now().time()
    start_time = time(0, 0)  # 12:00 AM
    end_time = time(5, 30)   # 5:30 AM

    if start_time <= current_time <= end_time:
        logger.error("Funds API unavailable between 12:00 AM and 5:30 AM IST")
        raise HTTPException(status_code=503, detail="Funds API unavailable (UDAPI100072)")

    try:
        url = f"{config['base_url']}/user/get-funds-and-margin"
        logger.debug(f"Funds Request: URL={url}")
        response = requests.get(url, headers=config['headers'])
        logger.debug(f"Funds Response: Status={response.status_code}, Body={response.text}")
        response.raise_for_status()
        return response.json().get("data", {})
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch funds: {str(e)}, Status={e.response.status_code if e.response else 500}, Body={e.response.text if e.response else ''}, Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error fetching funds: {str(e)}, Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def get_upstox_user_details(access_token: str) -> dict:
    logger.debug(f"Fetching user details with token: {access_token[:4]}...")
    try:
        config = get_upstox_config(access_token)
        url = f"{config['base_url']}/user/profile"
        logger.debug(f"User Profile Request: URL={url}")
        response = requests.get(url, headers=config['headers'])
        logger.debug(f"User Profile Response: Status={response.status_code}, Body={response.text}")
        response.raise_for_status()
        return response.json().get("data", {})
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch user details: {str(e)}, Status={e.response.status_code if e.response else 500}, Body={e.response.text if e.response else ''}, Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error fetching user details: {str(e)}, Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
