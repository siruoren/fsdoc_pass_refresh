# -*- coding: utf-8 -*-
"""SQLite 存储：认证信息 + 文档条目。"""
import os
import sqlite3
import threading
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "app.db"))

_lock = threading.Lock()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock, _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS auth_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                app_id TEXT NOT NULL,
                app_secret TEXT NOT NULL,
                updated_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                doc_token TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                title TEXT,
                cron TEXT,
                password TEXT,
                status TEXT DEFAULT '待刷新',
                status_msg TEXT,
                last_refresh TEXT,
                created_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS page_auth (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                password_hash TEXT NOT NULL,
                updated_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS api_auth (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                password_hash TEXT NOT NULL,
                updated_at TEXT
            )"""
        )
        # 旧库升级：entries 表补充 message 列
        cols = [r[1] for r in conn.execute("PRAGMA table_info(entries)")]
        if "message" not in cols:
            conn.execute("ALTER TABLE entries ADD COLUMN message TEXT")


# ---------- 认证信息 ----------

def save_auth(app_id: str, app_secret: str):
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO auth_config (id, app_id, app_secret, updated_at)
               VALUES (1, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET app_id = excluded.app_id,
                                            app_secret = excluded.app_secret,
                                            updated_at = excluded.updated_at""",
            (app_id, app_secret, _now()),
        )


def get_auth():
    with _connect() as conn:
        row = conn.execute("SELECT * FROM auth_config WHERE id = 1").fetchone()
        return dict(row) if row else None


def auth_status():
    auth = get_auth()
    if not auth:
        return {"configured": False, "app_id": None, "updated_at": None}
    return {"configured": True, "app_id": auth["app_id"], "updated_at": auth["updated_at"]}


# ---------- 页面访问密码 ----------

def get_page_auth():
    with _connect() as conn:
        row = conn.execute("SELECT * FROM page_auth WHERE id = 1").fetchone()
        return dict(row) if row else None


def save_page_password(password_hash):
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO page_auth (id, password_hash, updated_at)
               VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET password_hash = excluded.password_hash,
                                            updated_at = excluded.updated_at""",
            (password_hash, _now()),
        )


# ---------- API 认证密码 ----------

def get_api_auth():
    with _connect() as conn:
        row = conn.execute("SELECT * FROM api_auth WHERE id = 1").fetchone()
        return dict(row) if row else None


def save_api_password(password_hash):
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO api_auth (id, password_hash, updated_at)
               VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET password_hash = excluded.password_hash,
                                            updated_at = excluded.updated_at""",
            (password_hash, _now()),
        )


def clear_api_password():
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM api_auth WHERE id = 1")


# ---------- 条目 ----------

def add_entry(url, doc_token, doc_type, title, cron=None, entry_id=None):
    with _lock, _connect() as conn:
        if entry_id is not None:
            cur = conn.execute(
                """INSERT INTO entries (id, url, doc_token, doc_type, title, cron, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, '待刷新', ?)""",
                (entry_id, url, doc_token, doc_type, title, cron, _now()),
            )
        else:
            cur = conn.execute(
                """INSERT INTO entries (url, doc_token, doc_type, title, cron, status, created_at)
                   VALUES (?, ?, ?, ?, ?, '待刷新', ?)""",
                (url, doc_token, doc_type, title, cron, _now()),
            )
        return cur.lastrowid


def update_entry_cron(entry_id, cron):
    with _lock, _connect() as conn:
        conn.execute("UPDATE entries SET cron = ? WHERE id = ?", (cron, entry_id))


def update_entry_title(entry_id, title):
    with _lock, _connect() as conn:
        conn.execute("UPDATE entries SET title = ? WHERE id = ?", (title, entry_id))


def update_entry_message(entry_id, message):
    with _lock, _connect() as conn:
        conn.execute("UPDATE entries SET message = ? WHERE id = ?", (message, entry_id))


def delete_entry(entry_id):
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))


def get_entry(entry_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None


def list_entries():
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM entries ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def save_refresh_result(entry_id, password, status, status_msg, last_refresh=None):
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE entries
               SET password = ?, status = ?, status_msg = ?, last_refresh = ?
               WHERE id = ?""",
            (password, status, status_msg, last_refresh or _now(), entry_id),
        )
