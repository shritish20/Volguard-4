import upstox_client
from upstox_client import Configuration, ApiClient
from upstox_client.apis import OptionChainApi, OrderApi, MarketQuoteApi, UserApi, PortfolioApi
from upstox_client.rest import ApiException
import pandas as pd
from datetime import datetime
import retrying
from app.config import settings, logger
from fastapi import HTTPException
import json
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

def get_upstox_config(access_token: str) -> Configuration:
    configuration = Configuration()
    configuration.access_token = access_token
    configuration.base_path = settings.UPSTOX_BASE_URL
    structured_log("INFO", "Upstox configuration created", {"access_token": access_token[:4] + "..."})
    return configuration

@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
async def fetch_expiry(option_chain_api: OptionChainApi, instrument_key: str) -> Optional[str]:
    structured_log("DEBUG", "Fetching expiry", {"instrument_key": instrument_key})
    try:
        response = option_chain_api.get_option_contracts(instrument_key=instrument_key, api_version="2.0")
        contracts = response.get("data", [])
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
    except ApiException as e:
        structured_log("ERROR", f"Failed to fetch expiry: {e.body}", {"instrument_key": instrument_key, "status": e.status})
        raise HTTPException(status_code=e.status, detail=e.body)
    except Exception as e:
        structured_log("ERROR", f"Error fetching expiry: {str(e)}", {"instrument_key": instrument_key})
        raise HTTPException(status_code=500, detail=str(e))

@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
async def fetch_option_chain_raw(option_chain_api: OptionChainApi, instrument_key: str, expiry_date: str) -> list:
    structured_log("DEBUG", "Fetching option chain", {"instrument_key": instrument_key, "expiry_date": expiry_date})
    try:
        response = option_chain_api.get_option_chain(instrument_key=instrument_key, expiry_date=expiry_date, api_version="2.0")
        data = response.get('data', [])
        structured_log("INFO", "Option chain fetched successfully", {"instrument_key": instrument_key, "records": len(data)})
        return data
    except ApiException as e:
        structured_log("ERROR", f"Failed to fetch option chain: {e.body}", {"instrument_key": instrument_key, "expiry_date": expiry_date, "status": e.status})
        raise HTTPException(status_code=500, detail=e.body)
    except Exception as e:
        structured_log("ERROR", f"Error fetching option chain: {str(e)}", {"instrument_key": instrument_key, "expiry_date": expiry_date})
        raise HTTPException(status_code=500, detail=str(e))

@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
async def place_order_for_leg(access_token: str, leg: dict) -> dict:
    structured_log("DEBUG", "Placing order", {"instrument_key": leg.get("instrument_key"), "quantity": leg.get("quantity")})
    try:
        funds = await get_funds_and_margin(access_token)
        available_margin = funds.get('equity', {}).get('available_margin', 0.0)
        if available_margin <= 0:
            structured_log("ERROR", "Insufficient margin available", {"access_token": access_token[:4] + "..."})
            raise HTTPException(status_code=400, detail="Insufficient margin available")
        config = get_upstox_config(access_token)
        api_client = ApiClient(config)
        order_api = OrderApi(api_client)
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
        response = order_api.place_order(body=place_order_request, api_version="2.0")
        structured_log("INFO", "Order placed successfully", {"order_id": response.get('data', {}).get('order_id')})
        return response.get('data', {})
    except ApiException as e:
        structured_log("ERROR", f"Order placement failed: {e.body}", {"instrument_key": leg.get("instrument_key"), "status": e.status})
        raise HTTPException(status_code=e.status, detail=e.body)
    except Exception as e:
        structured_log("ERROR", f"Order placement error: {str(e)}", {"instrument_key": leg.get("instrument_key")})
        raise HTTPException(status_code=500, detail=str(e))

@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
async def fetch_trade_pnl(access_token: str, order_id: str) -> float:
    structured_log("DEBUG", "Fetching trade P&L", {"order_id": order_id})
    try:
        config = get_upstox_config(access_token)
        api_client = ApiClient(config)
        order_api = OrderApi(api_client)
        market_quote_api = MarketQuoteApi(api_client)
        trades = order_api.get_trade_book(api_version="2.0").get('data', [])
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
            ltp_data = market_quote_api.get_full_market_quote(instrument_keys=instrument_key, api_version="2.0")
            ltp = ltp_data.get('data', {}).get(instrument_key, {}).get('ltp', 0)
            if transaction_type == 'BUY':
                total_pnl += (ltp - avg_price) * quantity
            elif transaction_type == 'SELL':
                total_pnl += (avg_price - ltp) * quantity
        structured_log("INFO", "P&L calculated", {"order_id": order_id, "pnl": total_pnl})
        return total_pnl
    except ApiException as e:
        structured_log("ERROR", f"P&L fetch failed: {e.body}", {"order_id": order_id, "status": e.status})
        raise HTTPException(status_code=e.status, detail=e.body)
    except Exception as e:
        structured_log("ERROR", f"P&L fetch failed: {str(e)}", {"order_id": order_id})
        raise HTTPException(status_code=500, detail=str(e))

@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
async def get_upstox_user_details(access_token: str) -> Dict:
    structured_log("DEBUG", "Fetching user details", {"access_token": access_token[:4] + "..."})
    try:
        config = get_upstox_config(access_token)
        api_client = ApiClient(config)
        user_api = UserApi(api_client)
        portfolio_api = PortfolioApi(api_client)
        order_api = OrderApi(api_client)

        profile_data = user_api.get_profile(api_version="2.0").get('data', {})
        try:
            funds_data = user_api.get_user_fund_margin(segment="EQ", api_version="2.0").get('data', {})
        except ApiException as e:
            if "UDAPI100072" in str(e.body):
                structured_log("WARNING", "Funds API not available during this time window", {"error_code": "UDAPI100072"})
                funds_data = {"note": "Funds service unavailable between 12:00 AM and 5:30 AM IST."}
            else:
                raise HTTPException(status_code=e.status, detail=e.body)
        holdings_data = portfolio_api.get_holdings(api_version="2.0").get('data', [])
        positions_data = portfolio_api.get_positions(api_version="2.0").get('data', [])
        all_orders_data = order_api.get_order_book(api_version="2.0").get('data', [])
        trades_for_day_data = order_api.get_trade_book(api_version="2.0").get('data', [])

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
    except ApiException as e:
        structured_log("ERROR", f"User details fetch failed: {e.body}", {"status": e.status})
        raise HTTPException(status_code=e.status, detail=e.body)
    except Exception as e:
        structured_log("ERROR", f"User details fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
async def get_funds_and_margin(access_token: str) -> Dict:
    structured_log("DEBUG", "Fetching funds and margin", {"access_token": access_token[:4] + "..."})
    try:
        config = get_upstox_config(access_token)
        api_client = ApiClient(config)
        user_api = UserApi(api_client)
        funds_data = user_api.get_user_fund_margin(segment="EQ", api_version="2.0").get('data', {})
        structured_log("INFO", "Funds and margin fetched successfully", {"available_margin": funds_data.get('equity', {}).get('available_margin', 0.0)})
        return funds_data
    except ApiException as e:
        if "UDAPI100072" in str(e.body):
            structured_log("WARNING", "Funds API not available during this time window", {"error_code": "UDAPI100072"})
            return {"note": "Funds service unavailable between 12:00 AM and 5:30 AM IST."}
        structured_log("ERROR", f"Funds fetch failed: {e.body}", {"status": e.status})
        raise HTTPException(status_code=e.status, detail=e.body)
    except Exception as e:
        structured_log("ERROR", f"Funds fetch failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
