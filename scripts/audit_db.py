"""
Audit script: checks DB for poisoned/DUMMY entries and price integrity.
"""
import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'eod_bars.db')

def main():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: DB not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # List all tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r['name'] for r in cur.fetchall()]
    print(f"\n=== Tables in DB: {tables} ===\n")

    # ── century_compounder_cache ──
    if 'century_compounder_cache' in tables:
        # Inspect actual schema
        cur.execute("PRAGMA table_info(century_compounder_cache)")
        cols = [r['name'] for r in cur.fetchall()]
        print(f"  Columns: {cols}")

        cur.execute("SELECT COUNT(*) AS cnt FROM century_compounder_cache")
        total = cur.fetchone()['cnt']
        print(f"century_compounder_cache: {total} total entries")

        # DUMMY check
        cur.execute("SELECT COUNT(*) AS cnt FROM century_compounder_cache WHERE symbol LIKE 'DUMMY%'")
        dummy = cur.fetchone()['cnt']
        print(f"  DUMMY entries: {dummy}")

        # Find price/score column names
        price_col = next((c for c in cols if c in ('cmp', 'price', 'current_price', 'last_price')), None)
        score_col = next((c for c in cols if 'score' in c.lower() or 'conviction' in c.lower()), None)
        print(f"  Price col: {price_col}, Score col: {score_col}")

        # Sample symbols
        cur.execute(f"SELECT symbol FROM century_compounder_cache ORDER BY symbol LIMIT 30")
        rows = cur.fetchall()
        print(f"\n  First 30 symbols (alphabetical):")
        for r in rows:
            print(f"    {r['symbol']}")

        # Price integrity check if we found price col
        if price_col:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM century_compounder_cache WHERE {price_col} IS NULL OR {price_col} = 0")
            bad_prices = cur.fetchone()['cnt']
            print(f"\n  Entries with {price_col}=0 or NULL: {bad_prices}")
            if bad_prices > 0:
                cur.execute(f"SELECT symbol, {price_col} FROM century_compounder_cache WHERE {price_col} IS NULL OR {price_col} = 0 LIMIT 20")
                bad = cur.fetchall()
                for r in bad:
                    print(f"    ⚠️  {r['symbol']}: {price_col}={r[price_col]}")
    else:
        print("century_compounder_cache table not found")

    print("\n=== Audit complete ===")
    conn.close()

if __name__ == '__main__':
    main()
