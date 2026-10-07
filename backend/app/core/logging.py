import logging
import sys

from loguru import logger


class InterceptHandler(logging.Handler):
    """Route standard-library logging (uvicorn, fastapi) through Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    )
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
