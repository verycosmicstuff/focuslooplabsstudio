import os
import sys
import logging
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config import BASE_DIR, LOGS_DIR

LOG_FILE = LOGS_DIR / "focusloop.log"
if not LOG_FILE.exists() and (LOGS_DIR / "savespace.log").exists():
    LOG_FILE = LOGS_DIR / "savespace.log"

# Create root / focusloop logger
logger = logging.getLogger("focusloop")
logger.setLevel(logging.INFO)

# Avoid duplicate handlers on reload
if not logger.handlers:
    # 1. Rotating file handler (5 MB per file, 5 backups)
    file_handler = RotatingFileHandler(
        str(LOG_FILE),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    # 2. Console stream handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

def get_logger(sub_name: str = "") -> logging.Logger:
    if sub_name:
        return logging.getLogger(f"savespace.{sub_name}")
    return logger

def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    """Global hook to write any unhandled crash or exception into savespace.log."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Uncaught Exception Occurred:", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_uncaught_exception
