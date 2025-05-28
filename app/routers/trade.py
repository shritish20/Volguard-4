from fastapi import APIRouter, HTTPException, WebSocket
from app.config import logger
from app.models import OrderLeg, TradePnlRequest, UserDetailsInput, WebSocketRequest
from app.utils.upstox_helpers import place_order_for_leg, fetch_trade_pnl, get_funds_and_margin, get_upstox_config
from upstox_client import MarketDataStreamerV3, PortfolioDataStreamer, ApiClient

router = APIRouter()

@router.post("/place-order", summary="Place a trading order")
async def place_order(data: OrderLeg, token: UserDetailsInput):
    try:
        response = await place_order_for_leg(token.access_token, data.dict())
        return response
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Place order endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/trade-pnl", summary="Fetch P&L for an order")
async def get_trade_pnl(data: TradePnlRequest):
    try:
        pnl = await fetch_trade_pnl(data.access_token, data.order_id)
        return {"pnl": pnl}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Trade P&L endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/funds-margin", summary="Fetch funds and margin")
async def get_funds_margin(token: UserDetailsInput):
    try:
        funds = await get_funds_and_margin(token.access_token)
        return funds
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Funds and margin endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.websocket("/market-data")
async def websocket_market_data(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        request = WebSocketRequest(**data)
        config = get_upstox_config(request.access_token)
        streamer = MarketDataStreamerV3(ApiClient(config), request.instrument_keys, request.mode)
        def on_message(message):
            try:
                websocket.send_json({"type": "market_data", "data": message})
            except Exception as e:
                logger.error(f"WebSocket send error: {e}")
        def on_error(error):
            try:
                websocket.send_json({"type": "error", "data": str(error)})
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
        streamer.on("message", on_message)
        streamer.on("error", on_error)
        streamer.connect()
        while True:
            await websocket.receive_text()
    except Exception as e:
        logger.error(f"WebSocket market data error: {e}")
        await websocket.close()
    finally:
        streamer.disconnect()

@router.websocket("/portfolio-data")
async def websocket_portfolio_data(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        request = UserDetailsInput(**data)
        config = get_upstox_config(request.access_token)
        streamer = PortfolioDataStreamer(ApiClient(config), order_update=True, position_update=True)
        def on_message(message):
            try:
                websocket.send_json({"type": "portfolio_data", "data": message})
            except Exception as e:
                logger.error(f"WebSocket send error: {e}")
        def on_error(error):
            try:
                websocket.send_json({"type": "error", "data": str(error)})
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
        streamer.on("message", on_message)
        streamer.on("error", on_error)
        streamer.connect()
        while True:
            await websocket.receive_text()
    except Exception as e:
        logger.error(f"WebSocket portfolio error: {e}")
        await websocket.close()
    finally:
        streamer.disconnect()
