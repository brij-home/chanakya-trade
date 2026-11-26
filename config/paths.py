"""Shared filesystem paths for ChanakyaTrade runtime data."""

from __future__ import annotations

import os
from pathlib import Path


_BOOLEAN_ENV_SENTINELS = {"0", "1", "true", "false", "yes", "no", "on", "off"}


def app_data_dir() -> Path:
    """
    Return the writable app data directory.

    Defaults to ~/.trading_platform for desktop/CLI compatibility. Tests,
    CI, and containers can override this with TRADING_PLATFORM_HOME.
    """
    for env_name in ("TRADING_PLATFORM_DATA", "TRADING_PLATFORM_HOME"):
        raw = os.environ.get(env_name)
        if raw is None:
            continue
        cleaned = raw.strip()
        if cleaned and cleaned.lower() not in _BOOLEAN_ENV_SENTINELS:
            return Path(cleaned).expanduser()
    return Path.home() / ".trading_platform"


def app_data_path(*parts: str) -> Path:
    """Return a path inside the writable app data directory."""
    return app_data_dir().joinpath(*parts)


def pdf_output_dir() -> Path:
    """Return the directory used for primary PDF downloads/exports."""
    override = os.environ.get("TRADING_PLATFORM_PDF_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Desktop"
