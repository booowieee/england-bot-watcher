"""
Structured logging module for SWS Monitor Bot with Windows UTF-8 console safety.
"""
import io
import logging
import sys
from logging.handlers import RotatingFileHandler
from src.config import Config

# Ensure stdout and stderr use UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def setup_logger(name: str = "sws_monitor") -> logging.Logger:
    """Configures and returns a structured logger with console and rotating file handlers."""
    logger = logging.getLogger(name)
    level = logging.DEBUG if Config.DEBUG_MODE else logging.INFO
    logger.setLevel(level)

    if logger.handlers:
        return logger

    log_format = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler with UTF-8 encoding
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    # File Handler (rotating: max 10MB per file, up to 5 backups)
    log_file = Config.LOGS_DIR / "monitor.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)

    return logger


logger = setup_logger()
