"""
tests/test_observability_correlation.py
────────────────────────────────────────
Deterministic verification of correlation contextvars, institutional log filter,
and async propagation invariants.
"""

import asyncio
import logging
import pytest

from engine.observability import (
    InstitutionalCorrelationFilter,
    clear_correlation_context,
    get_current_correlation_id,
    get_current_correlation_symbol,
    install_institutional_correlation_filter,
    set_correlation_context,
)


@pytest.fixture(autouse=True)
def clean_context():
    """Ensure every test starts and ends with clean correlation context."""
    clear_correlation_context()
    yield
    clear_correlation_context()


def test_correlation_contextvars_get_and_set():
    """Verifies basic setting, getting, and clearing of correlation contextvars."""
    assert get_current_correlation_id() is None
    assert get_current_correlation_symbol() is None

    set_correlation_context(correlation_id="req-12345", symbol="RELIANCE")
    assert get_current_correlation_id() == "req-12345"
    assert get_current_correlation_symbol() == "RELIANCE"

    clear_correlation_context()
    assert get_current_correlation_id() is None
    assert get_current_correlation_symbol() is None


def test_correlation_filter_populates_record():
    """Verifies that InstitutionalCorrelationFilter enriches log records."""
    filt = InstitutionalCorrelationFilter()
    logger = logging.getLogger("test_corr_logger")
    record = logger.makeRecord("test_corr_logger", logging.INFO, "fn", 1, "test message", (), None)

    # When no context is set, defaults to '-'
    filt.filter(record)
    assert record.correlation_id == "-"
    assert record.symbol == "-"

    # When context is set, enriches with context values
    set_correlation_context(correlation_id="order-999", symbol="TCS")
    filt.filter(record)
    assert record.correlation_id == "order-999"
    assert record.symbol == "TCS"


def test_correlation_filter_preserves_explicit_attributes():
    """Explicitly supplied attributes on LogRecord should not be overwritten."""
    filt = InstitutionalCorrelationFilter()
    logger = logging.getLogger("test_corr_logger_explicit")
    record = logger.makeRecord(
        "test_corr_logger_explicit",
        logging.INFO,
        "fn",
        1,
        "test message",
        (),
        None,
        extra={"correlation_id": "custom-id", "symbol": "INFY"},
    )

    set_correlation_context(correlation_id="context-id", symbol="HDFCBANK")
    filt.filter(record)

    assert record.correlation_id == "custom-id"
    assert record.symbol == "INFY"


def test_install_institutional_correlation_filter_idempotent():
    """Verifies install_institutional_correlation_filter does not add duplicate filters."""
    test_logger_name = "test_idempotent_install"
    logger = logging.getLogger(test_logger_name)

    # Initial count
    initial_filters = [f for f in logger.filters if isinstance(f, InstitutionalCorrelationFilter)]
    assert len(initial_filters) == 0

    install_institutional_correlation_filter(test_logger_name)
    assert len([f for f in logger.filters if isinstance(f, InstitutionalCorrelationFilter)]) == 1

    # Second call must be a no-op
    install_institutional_correlation_filter(test_logger_name)
    assert len([f for f in logger.filters if isinstance(f, InstitutionalCorrelationFilter)]) == 1


def test_async_task_context_isolation():
    """ContextVar values must remain isolated across concurrent async tasks."""

    async def worker(cid: str, sym: str):
        set_correlation_context(correlation_id=cid, symbol=sym)
        await asyncio.sleep(0.01)
        assert get_current_correlation_id() == cid
        assert get_current_correlation_symbol() == sym

    async def main():
        await asyncio.gather(
            worker("cid-1", "NIFTY"),
            worker("cid-2", "BANKNIFTY"),
            worker("cid-3", "FINNIFTY"),
        )

    asyncio.run(main())


def test_formatted_log_output_with_filter():
    """Verifies formatted log output includes correlation_id and symbol."""
    filt = InstitutionalCorrelationFilter()
    formatter = logging.Formatter("[%(levelname)s] [%(correlation_id)s] [%(symbol)s] %(message)s")

    logger = logging.getLogger("test_formatted_log")
    record = logger.makeRecord(
        "test_formatted_log", logging.INFO, "fn", 1, "Order placed", (), None
    )

    set_correlation_context(correlation_id="req-abc", symbol="SBIN")
    filt.filter(record)

    formatted = formatter.format(record)
    assert formatted == "[INFO] [req-abc] [SBIN] Order placed"
