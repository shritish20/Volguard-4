import upstox_client
from upstox_client import Configuration, ApiClient, OptionsApi, OrderApiV3
from upstox_client.rest import ApiException
import requests
import json
import time
import pandas as pd
from datetime import datetime, timedelta
import retrying
from app.config import settings, logger

# Upstox SDK client configuration
def get_upstox_config(access_token: str):
    configuration = Configuration()
    configuration.access_token = access_token
    return configuration

@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
def fetch_expiry(options_api_client: OptionsApi, instrument_key: str):
    """Fetches nearest expiry date for a given instrument key."""
    try:
        response = options_api_client.get_option_contracts(instrument_key=instrument_key)
        contracts = response.to_dict().get("data", [])
        expiry_dates = set()
        for contract in contracts:
            exp = contract.get("expiry")
            if isinstance(exp, str):
                exp = datetime.strptime(exp, "%Y-%m-%d")
            expiry_dates.add(exp)
        expiry_list = sorted(expiry_dates)
        today = datetime.now()
        valid_expiries = [e.strftime("%Y-%m-%d") for e in expiry_list if e >= today]
        return valid_expiries[0] if valid_expiries else None
    except ApiException as e:
        logger.error(f"Expiry fetch failed for {instrument_key}: {e.body}")
        raise
    except Exception as e:
        logger.error(f"Expiry fetch error for {instrument_key}: {e}")
        raise

@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
def fetch_option_chain_raw(options_api_client: OptionsApi, instrument_key: str, expiry_date: str):
    """Fetches raw option chain data."""
    try:
        res = options_api_client.get_put_call_option_chain(instrument_key=instrument_key, expiry_date=expiry_date)
        return res.to_dict().get('data', [])
    except ApiException as e:
        logger.error(f"Option chain fetch failed for {instrument_key} on {expiry_date}: {e.body}")
        raise
    except Exception as e:
        logger.error(f"Option chain fetch error for {instrument_key} on {expiry_date}: {e}")
        raise

@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
def get_market_depth(access_token: str, instrument_token: str):
    """Fetches market depth for a given instrument token using direct requests."""
    try:
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        url = f"{settings.UPSTOX_BASE_URL}/market-quote/depth"
        params = {"instrument_key": instrument_token}
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json().get('data', {}).get(instrument_token, {}).get('depth', {})
        bid_volume = sum(item.get('quantity', 0) for item in data.get('buy', []))
        ask_volume = sum(item.get('quantity', 0) for item in data.get('sell', []))
        return {"bid_volume": bid_volume, "ask_volume": ask_volume}
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP Request error for depth fetch for {instrument_token}: {e}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error for depth fetch for {instrument_token}: {e}")
        raise
    except Exception as e:
        logger.error(f"Depth fetch error for {instrument_token}: {e}")
        raise

@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
async def place_order_for_leg(access_token: str, leg: dict):
    """Places a single order leg via Upstox API."""
    try:
        config = get_upstox_config(access_token)
        api_client = ApiClient(config)
        order_api_v3 = OrderApiV3(api_client)

        place_order_request_v3 = upstox_client.PlaceOrderV3Request(
            instrument_token=leg["instrument_key"],
            quantity=leg["quantity"],
            product=upstox_client.PlaceOrderV3Request.ProductEnum.I, # Intraday for now, adjust as needed
            order_type=upstox_client.PlaceOrderV3Request.OrderTypeEnum.MARKET,
            transaction_type=upstox_client.PlaceOrderV3Request.TransactionTypeEnum.BUY if leg["action"] == "BUY" else upstox_client.PlaceOrderV3Request.TransactionTypeEnum.SELL,
            price=leg.get("price", 0.0), # Only for LIMIT orders, 0 for MARKET
            trigger_price=leg.get("trigger_price", 0.0),
            validity=upstox_client.PlaceOrderV3Request.ValidityEnum.DAY,
            disclosed_quantity=leg.get("disclosed_quantity", 0),
            tag=leg.get("tag", "volguard")
        )
        response = await order_api_v3.place_order(place_order_request_v3) # Use await here
        return response.to_dict().get('data', {})
    except ApiException as e:
        logger.error(f"Order failed for {leg['instrument_key']}: Status {e.status}, Body: {e.body}")
        raise
    except Exception as e:
        logger.error(f"Order failed for {leg['instrument_key']}: {e}")
        raise

@retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
def fetch_trade_pnl(access_token: str, order_id: str):
    """Fetches P&L for a given order ID using direct requests."""
    try:
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        url = f"{settings.UPSTOX_BASE_URL}/order/trades?order_id={order_id}"
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        trades = res.json().get('data', [])

        total_pnl = 0
        for trade in trades:
            # Note: 'realized_pnl' is not standard for individual trade API.
            # This is a simplification. For actual P&L, you usually calculate from buy/sell avg prices.
            # Assuming for demo purposes that Upstox provides some P&L if trade is closed.
            # A more robust system would fetch individual trade details (quantity, price, type)
            # and then compute P&L against the order book.
            total_pnl += trade.get('realized_pnl', 0) or 0 # This field might not exist

        return total_pnl
    except Exception as e:
        logger.error(f"P&L fetch failed for order {order_id}: {e}")
        return 0

# @retrying.retry(stop_max_attempt_number=3, wait_fixed=2000)
async def get_upstox_user_details(access_token: str):
    """Fetches comprehensive user details from Upstox APIs."""
    try:
        config = get_upstox_config(access_token)
        api_client = ApiClient(config)

        user_api = upstox_client.UserApi(api_client)
        portfolio_api = upstox_client.PortfolioApi(api_client)
        order_api = upstox_client.OrderApi(api_client)

        profile_data = user_api.get_profile(api_version="v2").to_dict().get('data', {})
        funds_data = user_api.get_user_fund_margin(api_version="v2").to_dict().get('data', {})
        holdings_data = portfolio_api.get_holdings(api_version="v2").to_dict().get('data', [])
        positions_data = portfolio_api.get_positions(api_version="v2").to_dict().get('data', [])
        all_orders_data = order_api.get_order_book(api_version="v2").to_dict().get('data', [])
        trades_for_day_data = order_api.get_trade_history(api_version="v2").to_dict().get('data', [])

        return {
            "profile": profile_data,
            "funds": funds_data,
            "holdings": holdings_data,
            "positions": positions_data,
            "orders": all_orders_data,
            "trades": trades_for_day_data
        }

    except ApiException as e:
        logger.error(f"Upstox API Error fetching user details: Status {e.status}, Body: {e.body}")
        raise HTTPException(status_code=500, detail=f"User details endpoint error: {e.body}")
    except Exception as e:
        import traceback
        logger.error(f"User details fetch failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"User details endpoint error: {str(e)}")
