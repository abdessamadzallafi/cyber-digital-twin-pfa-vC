import logging
import os
from logging.handlers import RotatingFileHandler

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler("logs/backend.log", maxBytes=5_000_000, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("digital_twin")
