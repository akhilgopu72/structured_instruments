"""Migration: add account support.

Steps:
1. Create `account` table
2. For each existing user, insert a "Personal" account (type=personal)
3. Add `account_id` column to `position`, default to the user's Personal account
4. Drop old unique index `uq_user_instrument`
5. Create new unique index on `(account_id, instrument_id)`
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from structured_instruments.config import settings


def _get_db_path() -> str:
    """Extract the file path from the sqlite URL."""
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
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='account'")
        if cur.fetchone() is not None:
            print("Migration already applied (account table exists). Skipping.")
            return

        print("Applying migration: add_account_support")

        # 1. Create account table
        cur.execute("""
            CREATE TABLE account (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES user(id),
                name VARCHAR(100) NOT NULL,
                account_type VARCHAR(50) NOT NULL,
                UNIQUE(user_id, name)
            )
        """)
        print("  Created 'account' table.")

        # 2. For each existing user, insert a "Personal" account
        cur.execute("SELECT id FROM user")
        user_rows = cur.fetchall()
        for (user_id,) in user_rows:
            cur.execute(
                "INSERT INTO account (user_id, name, account_type) VALUES (?, 'Personal', 'personal')",
                (user_id,),
            )
            print(f"  Created 'Personal' account for user id={user_id}.")

        # 3. Add account_id column to position
        cur.execute("ALTER TABLE position ADD COLUMN account_id INTEGER REFERENCES account(id)")

        # Set account_id based on user_id -> account mapping
        cur.execute("""
            UPDATE position
            SET account_id = (
                SELECT account.id FROM account
                WHERE account.user_id = position.user_id
                AND account.name = 'Personal'
            )
        """)
        print("  Added account_id column to position table and populated values.")

        # 4. Drop old unique index
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='position'")
        indexes = cur.fetchall()
        for (idx_name,) in indexes:
            if idx_name and not idx_name.startswith("sqlite_") and idx_name == "uq_user_instrument":
                cur.execute(f"DROP INDEX IF EXISTS [{idx_name}]")
                print(f"  Dropped index: {idx_name}")

        # 5. Create new unique index on (account_id, instrument_id)
        cur.execute("""
            CREATE UNIQUE INDEX uq_account_instrument
            ON position (account_id, instrument_id)
        """)
        print("  Created unique index on (account_id, instrument_id).")

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
