import os
import sqlite3
from datetime import datetime

from config import DB_PATH

# цены храним в копейках целым числом: у float бывают ошибки округления
CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL,
    store           TEXT NOT NULL,
    external_id     TEXT,                       -- id товара на сайте магазина
    title           TEXT,
    threshold_kop   INTEGER,                    -- порог цены
    chat_id         INTEGER NOT NULL DEFAULT 0, -- пользователь телеграма, пригодится для бота
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    last_checked_at TEXT,
    last_status     TEXT,
    UNIQUE (url, chat_id)
);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    price_kop   INTEGER NOT NULL CHECK (price_kop > 0),
    checked_at  TEXT NOT NULL
);
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    is_new = not os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # чтобы обращаться к полям по имени: row["url"]
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(CREATE_TABLES)
    if is_new:
        print(f"Создана база данных: {DB_PATH}")
    return conn


def add_product(conn, url, store, external_id, threshold_kop, chat_id=0):
    # если такой товар уже есть, просто обновляем порог и снова включаем
    row = conn.execute("SELECT id FROM products WHERE url = ? AND chat_id = ?",
                       (url, chat_id)).fetchone()
    if row:
        conn.execute("UPDATE products SET threshold_kop = ?, is_active = 1 WHERE id = ?",
                     (threshold_kop, row["id"]))
        conn.commit()
        return row["id"]

    cur = conn.execute(
        "INSERT INTO products (url, store, external_id, threshold_kop, chat_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (url, store, external_id, threshold_kop, chat_id, now()))
    conn.commit()
    return cur.lastrowid


def get_products(conn):
    return conn.execute("SELECT * FROM products WHERE is_active = 1 ORDER BY id").fetchall()


def remove_product(conn, product_id):
    # сам товар и его историю не удаляем, просто перестаем проверять
    conn.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))
    conn.commit()


def save_price(conn, product_id, price_kop):
    conn.execute("INSERT INTO price_history (product_id, price_kop, checked_at) VALUES (?, ?, ?)",
                 (product_id, price_kop, now()))
    conn.commit()


def set_status(conn, product_id, status, title=None):
    if title:
        conn.execute("UPDATE products SET title = ? WHERE id = ?", (title, product_id))
    conn.execute("UPDATE products SET last_status = ?, last_checked_at = ? WHERE id = ?",
                 (status, now(), product_id))
    conn.commit()


def get_history(conn, product_id):
    return conn.execute("SELECT * FROM price_history WHERE product_id = ? ORDER BY id",
                        (product_id,)).fetchall()


def get_last_price(conn, product_id):
    row = conn.execute("SELECT price_kop FROM price_history WHERE product_id = ? "
                       "ORDER BY id DESC LIMIT 1", (product_id,)).fetchone()
    return row["price_kop"] if row else None
