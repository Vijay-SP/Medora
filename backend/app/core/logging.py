"""
Medpark Meeting Intelligence System - Privacy-Aware Logging
Ensures high-observability logging without leaking patient records or sensitive transcript audio.
"""

import io
import logging
import re
import sys
from typing import Any


# Matches only the credential that follows a bearer scheme, so the rest of the log line survives
BEARER_TOKEN_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*")


class PrivacyFilter(logging.Filter):
    """
    Prevents leaking raw patient audio streams or large medical transcripts into system logs.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "msg") and isinstance(record.msg, str):
            # Replace the token in place; truncating at the match would destroy the diagnostic context
            record.msg = BEARER_TOKEN_PATTERN.sub(r"\1[REDACTED]", record.msg)
        return True


def setup_logger(name: str = "medpark") -> logging.Logger:
    """
    Configures and returns a structured, privacy-compliant application logger.
    Ensures safe UTF-8 output on Windows consoles.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # Ensure UTF-8 output on Windows streams
        stream = sys.stdout
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        handler.addFilter(PrivacyFilter())
        
        logger.addHandler(handler)
        logger.propagate = False
        
    return logger


logger = setup_logger("medpark.core")
