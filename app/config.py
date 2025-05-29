import os
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler

load_dotenv()

class Settings:
    UPSTOX_ACCESS_TOKEN: str = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    UPSTOX_BASE_URL: str = "https://api.upstox.com"  # Fixed: Removed /v2
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./trades.db")
    NIFTY_HISTORICAL_DATA_URL: str = "https://raw.githubusercontent.com/shritish20/VolGuard/main/nifty_50.csv"
    XGBOOST_MODEL_URL: str = "https://drive.google.com/uc?export=download&id=1Gs86p1p8wsGe1lp498KC-OVn0e87Gv-R"

settings = Settings()

logger = logging.getLogger("VolGuardPro")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    '{"asctime": "%(asctime)s", "name": "%(name)s", "levelname": "%(levelname)s", "message": "%(message)s"}'
)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = RotatingFileHandler(
    "volguard_pro.log", maxBytes=5*1024*1024, backupCount=5
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
