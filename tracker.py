"""
Fiyat Takip Veritabanı — SQLite
Tablolar:
  watches  → agent + tur takip listesi
  prices   → fiyat geçmişi
"""

import sqlite3, os, logging
from datetime import datetime

log = logging.getLogger(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), 'tracker.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS watches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_phone TEXT    NOT NULL,
            tour_url    TEXT    NOT NULL,
            tour_name   TEXT    NOT NULL,
            source      TEXT    NOT NULL,
            last_price  REAL,
            last_check  TEXT,
            created_at  TEXT    DEFAULT (datetime('now')),
            active      INTEGER DEFAULT 1,
            UNIQUE(agent_phone, tour_url)
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            watch_id    INTEGER NOT NULL,
            price       REAL    NOT NULL,
            checked_at  TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY(watch_id) REFERENCES watches(id)
        );
        """)
    log.info("DB başlatıldı ✓")


def add_watch(agent_phone: str, tour_url: str, tour_name: str,
              source: str, current_price: float) -> tuple[bool, str]:
    """Takip ekle. (success, message)"""
    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO watches (agent_phone, tour_url, tour_name, source, last_price, last_check)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_phone, tour_url) DO UPDATE SET active=1
            """, (agent_phone, tour_url, tour_name, source, current_price, datetime.now().isoformat()))
        return True, f"✅ Takibe alındı: *{tour_name}* — £{current_price:.0f}"
    except Exception as e:
        log.error(f"add_watch hatası: {e}")
        return False, f"❌ Hata: {e}"


def remove_watch(agent_phone: str, tour_url: str) -> tuple[bool, str]:
    """Takibi sil (pasif yap)."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE watches SET active=0 WHERE agent_phone=? AND tour_url=? AND active=1",
            (agent_phone, tour_url)
        )
        if cur.rowcount:
            return True, "✅ Takip kaldırıldı."
        return False, "❌ Aktif takip bulunamadı."


def list_watches(agent_phone: str) -> list[dict]:
    """Agent'ın aktif takiplerini getir."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, tour_name, tour_url, source, last_price, last_check
            FROM watches
            WHERE agent_phone=? AND active=1
            ORDER BY created_at DESC
        """, (agent_phone,)).fetchall()
    return [dict(r) for r in rows]


def get_all_active_watches() -> list[dict]:
    """Tüm aktif takipleri getir (scheduler için)."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, agent_phone, tour_name, tour_url, source, last_price
            FROM watches WHERE active=1
        """).fetchall()
    return [dict(r) for r in rows]


def update_price(watch_id: int, new_price: float):
    """Fiyatı güncelle ve geçmişe ekle."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE watches SET last_price=?, last_check=? WHERE id=?",
            (new_price, now, watch_id)
        )
        conn.execute(
            "INSERT INTO price_history (watch_id, price) VALUES (?, ?)",
            (watch_id, new_price)
        )


def get_price_history(watch_id: int, limit: int = 10) -> list[dict]:
    """Fiyat geçmişini getir."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT price, checked_at FROM price_history
            WHERE watch_id=? ORDER BY checked_at DESC LIMIT ?
        """, (watch_id, limit)).fetchall()
    return [dict(r) for r in rows]


# DB'yi başlat
init_db()
