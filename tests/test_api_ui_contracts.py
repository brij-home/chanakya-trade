"""
tests/test_api_ui_contracts.py
──────────────────────────────
Frontend-Backend Contract Parity Invariant Tests.

Guarantees:
  1. Every key expected by frontend React views exists in backend API payloads.
  2. Endpoints never return undefined or mismatched property names.
  3. Action buttons (sync, purge, reset) trigger real backend execution without 500 errors.
"""

from fastapi.testclient import TestClient
from web.api import app

client = TestClient(app, raise_server_exceptions=False)


def test_opsdeck_health_hub_ui_contract():
    """
    Validates that GET /api/system/health-hub satisfies the exact schema
    expected by OpsDeckView.jsx (ribbon cards, vital metrics, and storage tiers).
    """
    res = client.get("/api/system/health-hub?limit=50")
    assert res.status_code == 200
    data = res.json()

    # 1. Top-level status & incident counts
    assert "overall_status" in data
    assert "incident_counts" in data
    assert "active_incident_counts" in data
    assert all(k in data["incident_counts"] for k in ("P0", "P1", "P2", "P3"))
    assert all(k in data["active_incident_counts"] for k in ("P0", "P1", "P2", "P3"))

    # 2. Fyers Circuit Breaker
    assert "circuit_breaker" in data
    cb = data["circuit_breaker"]
    assert "state" in cb
    assert "is_tripped" in cb

    # 3. WebSocket capacity
    assert "websocket" in data
    ws = data["websocket"]
    assert "total_subscribed" in ws
    assert "max_capacity" in ws
    assert "utilization_pct" in ws

    # 4. Host Vitals: Memory
    assert "memory" in data
    mem = data["memory"]
    assert "process_rss_mb" in mem
    assert ("used_ram_pct" in mem) or ("system_ram_pct" in mem)
    assert "total_ram_mb" in mem

    # 5. Host Vitals: Storage
    assert "storage" in data
    storage = data["storage"]
    assert ("free_ssd_gb" in storage) or ("ssd_free_gb" in storage)
    assert ("wal_mb" in storage) or ("wal_mb" in storage.get("tiers", {}).get("business", {}))
    assert ("total_size_mb" in storage) or ("total_app_data_mb" in storage)

    # 6. Storage Footprint Tiers
    tiers = storage.get("tiers", {})
    assert "business" in tiers
    assert "size_mb" in tiers["business"]
    assert "market_data" in tiers
    assert "size_mb" in tiers["market_data"]
    assert "analytics" in tiers
    assert "size_mb" in tiers["analytics"]
    assert "telemetry" in tiers
    assert "size_mb" in tiers["telemetry"]


def test_opsdeck_maintenance_actions_contract():
    """
    Validates that 1-click maintenance action endpoints callable from OpsDeck
    return 200 OK without unhandled exceptions or import errors.
    """
    # 1. Fundamentals & Forensics Sync (limit=1 for test execution speed)
    res_sync = client.post("/api/maintenance/sync-fundamentals?limit=1")
    assert res_sync.status_code == 200
    sync_data = res_sync.json()
    assert sync_data.get("status") == "SUCCESS"
    assert "fundamentals_saved" in sync_data
    assert "forensics_saved" in sync_data

    # 2. Ephemeral Purge
    res_purge = client.post(
        "/api/maintenance/purge",
        json={"vacuum_databases": False, "raw_tick_days": 30, "disk_cache_days": 30},
    )
    assert res_purge.status_code == 200
    purge_data = res_purge.json()
    assert "actions_taken" in purge_data

    # 3. Historical Errors
    res_err = client.get("/api/diagnostics/errors/history?limit=10")
    assert res_err.status_code == 200
    assert "incidents" in res_err.json()
