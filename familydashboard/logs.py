"""Logging via loguru.

Everything goes through loguru: our own ``logger`` calls and the standard
``logging`` records emitted by Flask, werkzeug, gunicorn and SQLAlchemy
(routed by ``InterceptHandler``).
"""

import inspect
import logging
import sys

from flask import Flask
from loguru import logger

FORMAT = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>"


class InterceptHandler(logging.Handler):
    """Forward standard-library log records to loguru (recipe from the loguru docs)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(app: Flask) -> None:
    level = app.config["LOG_LEVEL"].upper()
    logger.remove()
    logger.add(sys.stderr, level=level, format=FORMAT, backtrace=False, diagnose=False)
    if app.config.get("LOG_FILE"):
        logger.add(
            app.config["LOG_FILE"], level=level, rotation="10 MB", retention=5,
            backtrace=False, diagnose=False, enqueue=True,
        )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ("werkzeug", "gunicorn.error", "gunicorn.access", "sqlalchemy"):
        std = logging.getLogger(name)
        std.handlers = []
        std.propagate = True
    # SQL statement logging is very chatty; only show it when explicitly debugging.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO if level == "TRACE" else logging.WARNING)
