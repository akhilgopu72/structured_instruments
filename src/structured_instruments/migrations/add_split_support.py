"""Migration: add stock-split adjustment columns to instrument_underlying.

Adds 4 columns:
- split_adjustment_factor: cumulative split factor applied (default 1.0)
- original_initial_price: prospectus initial price (before any split adjustment)
- original_coupon_barrier_price: prospectus coupon barrier price
- original_downside_barrier_price: prospectus downside barrier price
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from structured_instruments.config import settings


def _get_db_path() -> str:
    url = settings.database_url
    return url.replace("sqlite:///", "")


def run() -> None:
    db_path = _get_db_path()
    if not Path(db_path).exists():
        print(f"Database not found at {db_path}. Run the app first to create it.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # Check if migration already applied
        cur.execute("PRAGMA table_info(instrument_underlying)")
        columns = {row[1] for row in cur.fetchall()}

        if "split_adjustment_factor" in columns:
            print("Migration already applied (split columns exist). Skipping.")
            return

        print("Applying migration: add_split_support")

        cur.execute(
            "ALTER TABLE instrument_underlying ADD COLUMN split_adjustment_factor REAL DEFAULT 1.0"
        )
        cur.execute(
            "ALTER TABLE instrument_underlying ADD COLUMN original_initial_price REAL"
        )
        cur.execute(
            "ALTER TABLE instrument_underlying ADD COLUMN original_coupon_barrier_price REAL"
        )
        cur.execute(
            "ALTER TABLE instrument_underlying ADD COLUMN original_downside_barrier_price REAL"
        )

        # Seed original_* columns with current values so they're never NULL
        cur.execute("""
            UPDATE instrument_underlying
            SET original_initial_price = initial_price,
                original_coupon_barrier_price = coupon_barrier_price,
                original_downside_barrier_price = downside_barrier_price
        """)

        conn.commit()
        print("  Added split_adjustment_factor, original_initial_price,")
        print("  original_coupon_barrier_price, original_downside_barrier_price columns.")
        print("  Seeded original_* columns with current values.")
        print("Migration completed successfully.")

    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
