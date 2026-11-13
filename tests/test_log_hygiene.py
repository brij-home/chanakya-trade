"""Third-party SDK loggers must stay inside app data and stay bounded."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import pytest

from config.log_hygiene import _MARKER, install

LOGGER_NAME = "ChanakyaLogHygieneTest"


@pytest.fixture
def sdk_logger():
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    yield logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _unbounded_handler(tmp_path, name="raw.log"):
    handler = logging.FileHandler(tmp_path / name, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    return handler


def test_replaces_unbounded_handler_with_rotating_one(sdk_logger, tmp_path):
    sdk_logger.addHandler(_unbounded_handler(tmp_path))

    rewritten = install(names=(LOGGER_NAME,), log_dir=tmp_path)

    assert rewritten == [LOGGER_NAME]
    handlers = [h for h in sdk_logger.handlers if isinstance(h, logging.FileHandler)]
    assert len(handlers) == 1
    handler = handlers[0]
    assert isinstance(handler, RotatingFileHandler)
    assert getattr(handler, _MARKER) is True
    assert handler.maxBytes > 0
    assert handler.backupCount >= 1
    assert handler.baseFilename.endswith(f"{LOGGER_NAME}.log")
    assert handler.level == logging.DEBUG
    assert handler.formatter is not None


def test_install_is_idempotent(sdk_logger, tmp_path):
    sdk_logger.addHandler(_unbounded_handler(tmp_path))
    install(names=(LOGGER_NAME,), log_dir=tmp_path)
    before = list(sdk_logger.handlers)

    rewritten = install(names=(LOGGER_NAME,), log_dir=tmp_path)

    assert rewritten == []
    assert sdk_logger.handlers == before


def test_duplicate_file_handlers_collapse_to_one(sdk_logger, tmp_path):
    sdk_logger.addHandler(_unbounded_handler(tmp_path, "one.log"))
    sdk_logger.addHandler(_unbounded_handler(tmp_path, "two.log"))

    install(names=(LOGGER_NAME,), log_dir=tmp_path)

    handlers = [h for h in sdk_logger.handlers if isinstance(h, logging.FileHandler)]
    assert len(handlers) == 1


def test_non_file_handlers_are_preserved(sdk_logger, tmp_path):
    stream = logging.StreamHandler()
    sdk_logger.addHandler(stream)
    sdk_logger.addHandler(_unbounded_handler(tmp_path))

    install(names=(LOGGER_NAME,), log_dir=tmp_path)

    assert stream in sdk_logger.handlers


def test_logger_without_file_handler_is_untouched(sdk_logger, tmp_path):
    stream = logging.StreamHandler()
    sdk_logger.addHandler(stream)

    assert install(names=(LOGGER_NAME,), log_dir=tmp_path) == []
    assert sdk_logger.handlers == [stream]


def test_rejects_invalid_rotation_bounds(tmp_path):
    with pytest.raises(ValueError):
        install(names=(LOGGER_NAME,), log_dir=tmp_path, max_bytes=0)
    with pytest.raises(ValueError):
        install(names=(LOGGER_NAME,), log_dir=tmp_path, backup_count=0)
