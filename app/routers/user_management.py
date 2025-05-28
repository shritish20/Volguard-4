from fastapi import APIRouter, HTTPException
from app.config import logger
from app.models import UserDetailsInput
from app.utils.upstox_helpers import get_upstox_user_details

router = APIRouter()

@router.post("/details", summary="Retrieves authenticated user's profile, funds, holdings, and positions")
async def get_user_details_endpoint(data: UserDetailsInput):
    try:
        details = await get_upstox_user_details(data.access_token)
        return details
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"User details endpoint error: {e}")
        raise HTTPException(status_code=500, detail=f"User details endpoint error: {str(e)}")
