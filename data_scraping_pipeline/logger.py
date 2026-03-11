import os
import sys
from loguru import logger

def setup_logger(log_level: str = "INFO"):
    """Setup logger for data scraping pipeline module."""
    # Create a logs directory if it doesn't exist
    LOG_DIR = "logs"
    os.makedirs(LOG_DIR, exist_ok=True)

    # Configure loguru logging
    logger.remove()  # Remove default handler

    logger.add(
        sys.stdout,  # Log to console
        format="{level} | {file} | {line} | {message}",
        level=log_level
    )

    logger.add(
        f"{LOG_DIR}/data_scraping.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {file} | {line} | {message}",
        rotation="00:00",  # Rotates every midnight
        retention="30 days",  # Keep logs for 30 days
        compression=None,  # Do not compress
        level=log_level,
        enqueue=True,  # Async logging
        backtrace=True,
        diagnose=True,
    )
    return logger
