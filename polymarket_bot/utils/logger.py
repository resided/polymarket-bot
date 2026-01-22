"""
Logging configuration.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
import json


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)
        
        return json.dumps(log_data)


class TradingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        level = record.levelname[0]
        
        extras = ""
        if hasattr(record, "trade_info"):
            t = record.trade_info
            extras = f" | {t['market_id'][:8]}... {t['side']} ${t['size']:.0f} @ {t['price']:.3f}"
        elif hasattr(record, "signal_info"):
            s = record.signal_info
            extras = f" | {s['strategy']} {s['market_id'][:8]}... {s['side']}"
        
        return f"{timestamp} | {level} | {record.name} | {record.getMessage()}{extras}"


def setup_logging(log_level: str = "INFO", log_file: str = None):
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler with trading formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(TradingFormatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s%(extras)s"
    ))
    root_logger.addHandler(console_handler)
    
    # JSON file handler (optional)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)
    
    # Suppress noisy libraries
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
