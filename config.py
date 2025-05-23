import os
from dotenv import load_dotenv
import logging

load_dotenv() # Load environment variables from .env file

class Settings:
    NGROK_AUTH_TOKEN: str = os.getenv("NGROK_AUTH_TOKEN", "")
    UPSTOX_ACCESS_TOKEN: str = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    UPSTOX_BASE_URL: str = "https://api.upstox.com/v2" # For v2 APIs
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./trades.db")
    NIFTY_HISTORICAL_DATA_URL: str = "https://raw.githubusercontent.com/shritish20/VolGuard/main/nifty_50.csv"
    XGBOOST_MODEL_URL: str = "https://drive.google.com/uc?export=download&id=1Gs86p1p8wsGe1lp498KC-OVn0e87Gv-R"

# Initialize settings
settings = Settings()

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("VolGuardPro")
