"""Bounded, app-owned log files for third-party SDK loggers.

The Fyers SDK attaches an unbounded logging.FileHandler to its own logger on
client construction and writes into the process working directory. A long-running
session (and a 5,000-test suite) therefore accumulates multi-hundred-megabyte
files inside the checkout, and each new client appends another handler to the
same logger, duplicating every line.

install() relocates those handlers under the app data directory, collapses
duplicates to a single handler and bounds growth with standard rotation. It is
safe to call repeatedly and leaves non-file handlers (stream, telemetry) alone.
"""

from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.paths import app_data_path

#: Logger names created by the Fyers SDK (API, data socket, order socket, TBT).
SDK_LOGGER_NAMES: tuple[str, ...] = (
    "FyersAPI",
    "FyersAPIRequest",
    "fyersDataSocket",
    "fyersOrderSocket",
    "fyersTBTSocket",
)

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5
_MARKER = "_chanakya_bounded_handler"
_INSTALL_LOCK = threading.Lock()


def _bounded_handler(
    logger_name: str,
    *,
    log_dir: Path,
    max_bytes: int,
    backup_count: int,
    template: logging.Handler | None = None,
) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        log_dir / f"{logger_name.replace('.', '_')}.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    setattr(handler, _MARKER, True)
    if template is not None:
        handler.setLevel(template.level)
        if template.formatter is not None:
            handler.setFormatter(template.formatter)
    return handler


def install(
    *,
    log_dir: Path | str | None = None,
    names: tuple[str, ...] = SDK_LOGGER_NAMES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> list[str]:
    """Bound the SDK loggers. Returns the logger names that were rewritten."""
    if max_bytes <= 0 or backup_count < 1:
        raise ValueError("Log rotation requires max_bytes > 0 and backup_count >= 1")
    target_dir = Path(log_dir) if log_dir is not None else app_data_path("logs")
    target_dir.mkdir(parents=True, exist_ok=True)

    rewritten: list[str] = []
    with _INSTALL_LOCK:
        for name in names:
            if _install_one(
                name,
                log_dir=target_dir,
                max_bytes=max_bytes,
                backup_count=backup_count,
            ):
                rewritten.append(name)
    return rewritten


def _install_one(name: str, *, log_dir: Path, max_bytes: int, backup_count: int) -> bool:
    logger = logging.getLogger(name)
    file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
    if not file_handlers:
        return False
    already_bounded = [
        h
        for h in file_handlers
        if isinstance(h, RotatingFileHandler) and getattr(h, _MARKER, False)
    ]
    keep = (
        already_bounded[0]
        if already_bounded
        else _bounded_handler(
            name,
            log_dir=log_dir,
            max_bytes=max_bytes,
            backup_count=backup_count,
            template=file_handlers[0],
        )
    )
    for handler in file_handlers:
        if handler is keep:
            continue
        logger.removeHandler(handler)
        try:
            handler.close()
        except OSError as exc:  # pragma: no cover - platform dependent
            logging.getLogger(__name__).debug(
                "[LogHygiene] Could not close superseded handler for %s: %s", name, exc
            )
    if not already_bounded:
        logger.addHandler(keep)
        return True
    return len(already_bounded) > 1
