"""Authentication and SQLite database setup."""
from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Optional, Tuple

import bcrypt

from config import DATABASE_PATH, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_NAME, DEFAULT_ADMIN_PASSWORD, MOI_EMAIL_DOMAIN


def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DATABASE_PATH, check_same_thread=False)


def init_database() -> None:
    """Create users table and add the first admin account when the DB is empty."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
        """
    )
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        password_hash = bcrypt.hashpw(DEFAULT_ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt())
        cur.execute(
            "INSERT INTO users (email, password_hash, full_name) VALUES (?, ?, ?)",
            (DEFAULT_ADMIN_EMAIL, password_hash, DEFAULT_ADMIN_NAME),
        )
        conn.commit()
    conn.close()


def validate_email_domain(email: str) -> bool:
    if not email or "@" not in email:
        return False
    return email.rsplit("@", 1)[1].lower() == MOI_EMAIL_DOMAIN


def authenticate_user(email: str, password: str) -> Tuple[Optional[dict], Optional[str]]:
    """Return the user dictionary if authentication succeeds."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, email, password_hash, full_name FROM users WHERE email = ?", (email,))
    user = cur.fetchone()

    if not user:
        conn.close()
        return None, "Invalid email or password"

    user_id, user_email, password_hash, full_name = user
    if bcrypt.checkpw(password.encode("utf-8"), password_hash):
        cur.execute("UPDATE users SET last_login = ? WHERE id = ?", (dt.datetime.now(), user_id))
        conn.commit()
        conn.close()
        return {"id": user_id, "email": user_email, "full_name": full_name}, None

    conn.close()
    return None, "Invalid email or password"
