from fastapi import APIRouter, HTTPException
from app.config import logger
from app.models import OrderLeg, TradePnlRequest, UserDetailsInput
from app.utils.upstox_helpers import place_order_for_leg, fetch_trade_pnl, get_funds_and_margin, get_upstox_config

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
