import requests
import json
from datetime import datetime
import pandas as pd
from fastapi import HTTPException
from retrying import retry
from app.config import settings, logger
from typing import Optional, Dict

def structured_log(level: str, message: str, extra: dict = None):
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": message,
        **(extra or {})
    }
    logger.log(
        getattr(logger, level.lower())(json.dumps(log_data))
        if level.lower() in ["debug", "info", "error"]
        else logger.info(json.dumps(log_data))
    )

def get_upstox_config(access_token: str) -> dict:
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    base_url = settings.UPSTOX_BASE_URL  # Assumed as https://api.upstox.com
    structured_log("INFO", "Upstox configuration created", {"access_token": access_token[:4] + "..."})
    return {"base_url": base_url, "headers": headers}

@retry(stop_max_attempt_number=3, wait_fixed=2000)
async def fetch_expiry(config: dict, instrument_key: str) -> Optional[str]:
    structured_log("DEBUG", "Fetching expiry", {"instrument_key": instrument_key})
    try:
        url = f"{config['base_url']}/v2/option/contract"
        params = {'instrument_key': instrument_key}
        response = requests.get(url, headers=config['headers'], params=params)
        response.raise_for_status()
        contracts = response.json().get("data", [])
        expiry_dates = set()
        for contract in contracts:
            expiry = contract.get("expiry")
            if isinstance(expiry, str):
                expiration_date = datetime.strptime(expiry, "%Y-%m-%d")
                expiry_dates.add(expiration_date)
        expiry_list = sorted(expiry_dates)
        today = datetime.now()
        valid_expiries = [expiration_date.strftime("%Y-%m-%d") for expiration_date in expiry_list if expiration_date >= today]
        if valid_expiries:
            structured_log("INFO", "Expiry fetched successfully", {"instrument_key": instrument_key, "expiry": valid_expiries[0]})
            return valid_expiries[0]
        structured_log("ERROR", "No valid expiry dates found", {"instrument_key": instrument_key})
        return None
    except requests.exceptions.RequestException as e:
        structured_log("ERROR", f"Failed to fetch expiry: {str(e)}", {"instrument_key": instrument_key})
        raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))
    except Exception as e:
        structured_log("ERROR", f"Error fetching expiry: {str(e)}", {"instrument_key": instrument_key})
        raise HTTPException(status_code=500, detail=str(e))

@retry(stop_max_attempt_number=3, wait_fixed=2000)
async def fetch_option_chain_raw(config: dict, instrument_key: str, expiry_date: str) -> list:
    structured_log("DEBUG", "Fetching option chain", {"instrument_key": instrument_key, "expiry_date": expiry_date})
    try:
        url = f"{config['base_url']}/v2/option/chain"
        params = {'instrument_key': instrument_key, 'expiry_date': expiry_date}
        response = requests.get(url, headers=config['headers'], params=params)
        response.raise_for_status()
        data = response.json().get('data', [])
        structured_log("INFO", "Option chain fetched successfully", {"instrument_key": instrument_key, "records": len(data)})
        return data
    except requests.exceptions.RequestException as e:
        structured_log("ERROR", f"Failed to fetch option chain: {str(e)}", {"instrument_key": instrument_key, "expiry_date": expiry_date})
        raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))
    except Exception as e:
        structured_log("ERROR", f"Error fetching option chain: {str(e)}", {"instrument_key": instrument_key, "expiry_date": expiry_date})
        raise HTTPException(status_code=500, detail=str(e))

@retry(stop_max_attempt_number=3, wait_fixed=2000)
async def place_order_for_leg(access_token: str, leg: dict) -> dict:
    structured_log("DEBUG", "Placing order", {"instrument_key": leg.get("instrument_key"), "quantity": leg.get("quantity")})
    try:
        funds = await get_funds_and_margin(access_token)
        available_margin = funds.get('equity', {}).get('available_margin', 0.0)
        if available_margin <= 0:
            structured_log("ERROR", "Insufficient margin available", {"access_token": access_token[:4] + "..."})
            raise HTTPException(status_code=400, detail="Insufficient margin available")
        config = get_upstox_config(access_token)
        url = f"{config['base_url']}/v2/order/place"
        place_order_request = {
            "instrument_key": leg["instrument_key"],
            "quantity": leg["quantity"],
            "product": "I",
            "order_type": "MARKET",
            "transaction_type": "BUY" if leg["action"].upper() == "BUY" else "SELL",
            "price": leg.get("price", 0.0),
            "trigger_price": leg.get("trigger_price", 0.0),
            "validity": "DAY",
            "disclosed_quantity": leg.get("disclosed_quantity", 0),
            "tag": leg.get("tag", "volguard"),
            "is_amo": False
        }
        response = requests.post(url, headers=config['headers'], json=place_order_request)
        response.raise_for_status()
        data = response.json().get('data', {})
        structured_log("INFO", "Order placed successfully", {"order_id": data.get('order_id')})
        return data
    except requests.exceptions.RequestException as e:
        structured_log("ERROR", f"Order placement failed: {str(e)}", {"instrument_key": leg.get("instrument_key")})
        raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))
    except Exception as e:
        structured_log("ERROR", f"Order placement error: {str(e)}", {"instrument_key": leg.get("instrument_key")})
        raise HTTPException(status_code=500, detail=str(e))

@retry(stop_max_attempt_number=3, wait_fixed=2000)
async def fetch_trade_pnl(access_token: str, order_id: str) -> float:
    structured_log("DEBUG", "Fetching trade P&L", {"order_id": order_id})
    try:
        config = get_upstox_config(access_token)
        # Fetch trade book
        trade_url = f"{config['base_url']}/v2/trade/trade-book"
        trade_response = requests.get(trade_url, headers=config['headers'])
        trade_response.raise_for_status()
        trades = trade_response.json().get('data', [])
        total_pnl = 0.0
        for trade in trades:
            if trade.get('order_id') != order_id:
                continue
            avg_price = float(trade.get('average_price', 0))
            quantity = int(trade.get('quantity', 0))
            transaction_type = trade.get('transaction_type', '').upper()
            instrument_key = trade.get('instrument_key', '')
            if not instrument_key:
                continue
            # Fetch LTP
            quote_url = f"{config['base_url']}/v2/market-quote/quotes"
            params = {'instrument_key': instrument_key}
            quote_response = requests.get(quote_url, headers=config['headers'], params=params)
            quote_response.raise_for_status()
            ltp = quote_response.json().get('data', {}).get(instrument_key, {}).get('ltp', 0)
            if transaction_type == 'BUY':
                total_pnl += (ltp - avg_price) * quantity
            elif transaction_type == 'SELL':
                total_pnl += (avg_price - ltp) * quantity
        structured_log("INFO", "P&L calculated", {"order_id": order_id, "pnl": total_pnl})
        return total_pnl
    except requests.exceptions.RequestException as e:
        structured_log("ERROR", f"P&L fetch failed: {str(e)}", {"order_id": order_id})
        raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))
    except Exception as e:
        structured_log("ERROR", f"P&L fetch failed: {str(e)}", {"order_id": order_id})
        raise HTTPException(status_code=500, detail=str(e))

@retry(stop_max_attempt_number=3, wait_fixed=2000)
async def get_upstox_user_details(access_token: str) -> Dict:
    structured_log("DEBUG", "Fetching user details", {"access_token": access_token[:4] + "..."})
    try:
        config = get_upstox_config(access_token)
        # Fetch profile
        profile_url = f"{config['base_url']}/v2/user/profile"
        profile_response = requests.get(profile_url, headers=config['headers'])
        profile_response.raise_for_status()
        profile_data = profile_response.json().get('data', {})
        # Fetch funds
        funds_url = f"{config['base_url']}/v2/user/get-funds-and-margin"
        try:
            funds_response = requests.get(funds_url, headers=config['headers'])
            funds_response.raise_for_status()
            funds_data = funds_response.json().get('data', {})
        except requests.exceptions.RequestException as e:
            if "UDAPI100072" in str(e):
                structured_log("WARNING", "Funds API not available during this time window", {"error_code": "UDAPI100072"})
                funds_data = {"note": "Funds service unavailable between 12:00 AM and 5:30 AM IST."}
            else:
                raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))
        # Fetch holdings
        holdings_url = f"{config['base_url']}/v2/portfolio/long-term-holdings"
        holdings_response = requests.get(holdings_url, headers=config['headers'])
        holdings_response.raise_for_status()
        holdings_data = holdings_response.json().get('data', [])
        # Fetch positions
        positions_url = f"{config['base_url']}/v2/portfolio/short-term-positions"
        positions_response = requests.get(positions_url, headers=config['headers'])
        positions_response.raise_for_status()
        positions_data = positions_response.json().get('data', [])
        # Fetch orders
        orders_url = f"{config['base_url']}/v2/order/book"
        orders_response = requests.get(orders_url, headers=config['headers'])
        orders_response.raise_for_status()
        all_orders_data = orders_response.json().get('data', [])
        # Fetch trades
        trades_url = f"{config['base_url']}/v2/trade/trade-book"
        trades_response = requests.get(trades_url, headers=config['headers'])
        trades_response.raise_for_status()
        trades_for_day_data = trades_response.json().get('data', [])

        details = {
            "profile": profile_data,
            "funds": funds_data,
            "holdings": holdings_data,
            "positions": positions_data,
            "orders": all_orders_data,
            "trades": trades_for_day_data
        }
        structured_log("INFO", "User details fetched successfully", {"profile_email": profile_data.get('email', 'N/A')})
        return details
    except requests.exceptions.RequestException as e:
        structured_log("ERROR", f"User details fetch failed: {str(e)}", {"status": e.response.status_code if e.response else 500})
        raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))
    except Exception as e:
        structured_log("ERROR", f"User details fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@retry(stop_max_attempt_number=3, wait_fixed=2000)
async def get_funds_and_margin(access_token: str) -> Dict:
    structured_log("DEBUG", "Fetching funds and margin", {"access_token": access_token[:4] + "..."})
    try:
        config = get_upstox_config(access_token)
        funds_url = f"{config['base_url']}/v2/user/get-funds-and-margin"
        response = requests.get(funds_url, headers=config['headers'])
        response.raise_for_status()
        funds_data = response.json().get('data', {})
        structured_log("INFO", "Funds and margin fetched successfully", {"available_margin": funds_data.get('equity', {}).get('available_margin', 0.0)})
        return funds_data
    except requests.exceptions.RequestException as e:
        if "UDAPI100072" in str(e):
            structured_log("WARNING", "Funds API not available during this time window", {"error_code": "UDAPI100072"})
            return {"note": "Funds service unavailable between 12:00 AM and 5:30 AM IST."}
        structured_log("ERROR", f"Funds fetch failed: {str(e)}", {"status": e.response.status_code if e.response else 500})
        raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))
    except Exception as e:
        structured_log("ERROR", f"Funds fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
