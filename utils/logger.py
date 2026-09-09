"""Application-wide logging setup."""
from __future__ import annotations

import logging
import sys

from config import LOG_DIR, LOG_LEVEL, TELEGRAM_BOT_TOKEN

_configured = False


def setup_logging() -> None:
    """Configure console + logs/application.log + logs/errors.log.

    Safe to call multiple times.
    Rule: never log tokens, passwords, account numbers or secrets.
    """
    global _configured
    if _configured:
        return

    # Make unicode symbols safe even when output is redirected to a file.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    LOG_DIR.mkdir(exist_ok=True)
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    app_file = logging.FileHandler(LOG_DIR / "application.log", encoding="utf-8")
    app_file.setFormatter(fmt)
    root.addHandler(app_file)

    err_file = logging.FileHandler(LOG_DIR / "errors.log", encoding="utf-8")
    err_file.setLevel(logging.ERROR)
    err_file.setFormatter(fmt)
    root.addHandler(err_file)

    mask = _secret_mask_filter()
    for h in (console, app_file, err_file):
        if mask:
            h.addFilter(mask)

    _configured = True

def _secret_mask_filter() -> logging.Filter | None:
    """Scrub the bot token from every log record (httpx logs full URLs)."""
    token = TELEGRAM_BOT_TOKEN
    if not token:
        return None

    class _Mask(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            if token in msg:
                record.msg = msg.replace(token, "***")
                record.args = None
            return True
    return _Mask()