"""Migration: add multi-user support.

Steps:
1. Create `user` table
2. Insert a "Default" user (id=1)
3. Add `user_id` column to `position` with default=1
4. Drop old unique index on `position.instrument_id`
5. Create new unique index on `(user_id, instrument_id)`
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from structured_instruments.config import settings


def _get_db_path() -> str:
    """Extract the file path from the sqlite URL."""
    url = settings.database_url
    # sqlite:///data/structured_instruments.db -> data/structured_instruments.db
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
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user'")
        if cur.fetchone() is not None:
            print("Migration already applied (user table exists). Skipping.")
            return

        print("Applying migration: add_user_support")

        # 1. Create user table
        cur.execute("""
            CREATE TABLE user (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE
            )
        """)
        print("  Created 'user' table.")

        # 2. Insert default user
        cur.execute("INSERT INTO user (id, name) VALUES (1, 'Default')")
        print("  Inserted 'Default' user (id=1).")

        # 3. Add user_id column to position with default=1
        cur.execute("ALTER TABLE position ADD COLUMN user_id INTEGER DEFAULT 1 REFERENCES user(id)")
        # Set all existing positions to user_id=1
        cur.execute("UPDATE position SET user_id = 1 WHERE user_id IS NULL")
        print("  Added user_id column to position table.")

        # 4. Drop old unique index on instrument_id (SQLite doesn't support DROP INDEX
        # on implicit unique constraints, so we rebuild the table)
        # First, check existing indexes
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='position'")
        indexes = cur.fetchall()
        for (idx_name,) in indexes:
            if idx_name and not idx_name.startswith("sqlite_"):
                cur.execute(f"DROP INDEX IF EXISTS [{idx_name}]")
                print(f"  Dropped index: {idx_name}")

        # 5. Create new unique index on (user_id, instrument_id)
        cur.execute("""
            CREATE UNIQUE INDEX uq_user_instrument
            ON position (user_id, instrument_id)
        """)
        print("  Created unique index on (user_id, instrument_id).")

        conn.commit()
        print("Migration completed successfully.")

    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
