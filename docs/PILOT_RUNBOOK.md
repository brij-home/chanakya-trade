# Personal Pilot Runbook

This runbook keeps the initial rollout intentionally small: trustworthy EOD research first, then observable real-time data, paper trading, and finally limited user-confirmed cash-equity execution.

## 1. Install and start safely

On Windows, run `scripts\bootstrap.ps1` once. It repairs a stale virtual environment and installs the development dependencies. Start in the default safe mode:

```powershell
.\scripts\test.ps1
.venv\Scripts\python.exe -m app.main --no-broker
```

Keep `PILOT_PROFILE=OBSERVE` and `PILOT_ALLOW_LIVE_EXECUTION=0` in `.env` during account setup, EOD research, and paper validation.

## 2. Configure data and execution deliberately

1. Connect Shoonya after the account is active. Keep its credentials only in the local keychain or `.env`; never commit them.
2. Explicitly select the data provider and execution provider in the app. Connecting a second broker never changes either route.
3. Verify the UI’s source status. `LIVE` means a current provider event; `DELAYED`, `EOD`, `DEGRADED`, and `UNAVAILABLE` are not interchangeable.
4. Treat a data-provider outage as observation-only: do not increase risk; preserve the ability to cancel or exit through the selected execution broker.

## 3. EOD research and replay

- Run scans and backtests from versioned EOD snapshots.
- Record the snapshot ID and as-of date alongside any decision journal entry.
- Do not use an incomplete current-day candle in a backtest unless live-candle enrichment was explicitly requested and labelled.
- Independently compare the primary source with an EOD secondary source before trusting an unusual close, volume, split, or corporate-action day.

## 4. Shadow paper-trading acceptance

Run paper trades for several normal, volatile, and degraded-data sessions. Before live use, confirm:

- Quote source, provider and age are visible on every decision screen.
- Reconnect/resubscribe behaviour is recorded in provider health and telemetry.
- No `UNKNOWN_FREEZE` order remains unresolved.
- Paper fills, expected slippage and subsequent observed market prices are journaled.
- Broker orderbook polling maps each submitted/cancelled order back to the local ledger.

## 5. Establish reconciliation baseline

Before the first live order, record the opening cash known at the start of the pilot through `POST /api/reconciliation/baseline`. This is intentionally manual: copying today’s broker balance into the internal ledger would make reconciliation meaningless.

After the baseline exists, use `GET /api/reconciliation` before the session, after any live order/cancel, and before market close. A result of `UNAVAILABLE` means evidence is missing; it is not a clean reconciliation.

## 6. Limited live pilot

Only after shadow acceptance is documented:

1. Set `TRADING_MODE=EXECUTE`, `ALLOW_LIVE_TRADING=1`, and `PILOT_ALLOW_LIVE_EXECUTION=1` locally.
2. Keep the default `PILOT_ALLOWED_SEGMENTS=EQUITY_DELIVERY`, `PILOT_ALLOWED_PRODUCTS=CNC`, and a small `PILOT_MAX_ORDER_NOTIONAL`.
3. Use manual server-bound preview confirmation for every order.
4. Never enable automatic alternate-broker routing. A secondary feed is validation/observation only.
5. Keep F&O execution disabled until the active broker has supplied a verified token, lot size and tick size for the exact contract.

## 7. Retention and review

- EOD snapshots: retain locally long term.
- Raw ticks: `RAW_TICK_RETENTION_DAYS` is bounded between 7 and 30 days (default 14).
- Orders, fills, reconciliation reports and audit records: retain at least 90 days.
- Review provider health, data-quality flags, reconciliation outcomes and trade journal weekly before increasing scope.
