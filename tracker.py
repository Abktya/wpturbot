"""
Fiyat Takip Veritabanı — Kriter Bazlı Takip
Tablolar:
  watch_configs  → agent'ın arama kriterleri (dest, ay, bütçe, keyword)
  watch_results  → bulunan turlar + son fiyatlar
  price_history  → fiyat geçmişi
"""

import sqlite3, os, logging, json
from datetime import datetime

log = logging.getLogger(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), 'tracker.db')

MONTH_TR = {
    'ocak':1,'şubat':2,'subat':2,'mart':3,'nisan':4,
    'mayıs':5,'mayis':5,'haziran':6,'temmuz':7,
    'ağustos':8,'agustos':8,'eylül':9,'eylul':9,
    'ekim':10,'kasım':11,'kasim':11,'aralık':12,'aralik':12
}
MONTH_TR_REV = {v:k.capitalize() for k,v in MONTH_TR.items() if not any(c in k for c in ['ı','ş','ğ','ü','ö','ç'])}
MONTH_TR_REV.update({1:'Ocak',2:'Şubat',3:'Mart',4:'Nisan',5:'Mayıs',6:'Haziran',
                     7:'Temmuz',8:'Ağustos',9:'Eylül',10:'Ekim',11:'Kasım',12:'Aralık'})


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS watch_configs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_phone  TEXT    NOT NULL,
            dest_key     TEXT    NOT NULL,
            month_num    INTEGER,           -- NULL = tüm aylar
            budget_gbp   REAL,              -- NULL = sınırsız
            keyword      TEXT    DEFAULT '',-- boş = tüm turlar
            label        TEXT    NOT NULL,  -- insan okunabilir açıklama
            last_check   TEXT,
            created_at   TEXT DEFAULT (datetime('now')),
            active       INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS watch_results (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            config_id    INTEGER NOT NULL,
            tour_name    TEXT    NOT NULL,
            tour_url     TEXT    NOT NULL,
            source       TEXT    NOT NULL,
            start_date   TEXT,
            last_price   REAL,
            UNIQUE(config_id, tour_url),
            FOREIGN KEY(config_id) REFERENCES watch_configs(id)
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            result_id    INTEGER NOT NULL,
            price        REAL    NOT NULL,
            checked_at   TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(result_id) REFERENCES watch_results(id)
        );
        """)
    log.info("DB başlatıldı ✓")


def add_watch_config(agent_phone: str, dest_key: str, month_num: int | None,
                     budget_gbp: float | None, keyword: str, label: str) -> tuple[bool, int | None, str]:
    """Yeni takip kriteri ekle."""
    try:
        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO watch_configs
                    (agent_phone, dest_key, month_num, budget_gbp, keyword, label)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (agent_phone, dest_key, month_num, budget_gbp, keyword.lower().strip(), label))
            return True, cur.lastrowid, "✅ Takip oluşturuldu."
    except Exception as e:
        log.error(f"add_watch_config hatası: {e}")
        return False, None, f"❌ Hata: {e}"


def list_configs(agent_phone: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, label, dest_key, month_num, budget_gbp, keyword,
                   last_check, active,
                   (SELECT COUNT(*) FROM watch_results WHERE config_id=wc.id) as tour_count
            FROM watch_configs wc
            WHERE agent_phone=? AND active=1
            ORDER BY created_at DESC
        """, (agent_phone,)).fetchall()
    return [dict(r) for r in rows]


def remove_config(agent_phone: str, config_id: int) -> tuple[bool, str]:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE watch_configs SET active=0 WHERE id=? AND agent_phone=?",
            (config_id, agent_phone)
        )
        if cur.rowcount:
            return True, "✅ Takip kaldırıldı."
        return False, "❌ Takip bulunamadı."


def get_all_active_configs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM watch_configs WHERE active=1"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_tour_result(config_id: int, tour_name: str, tour_url: str,
                       source: str, start_date: str, price_gbp: float) -> tuple[float | None, int]:
    """
    Turu güncelle veya ekle.
    Dönüş: (eski_fiyat | None, result_id)
    """
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, last_price FROM watch_results WHERE config_id=? AND tour_url=?",
            (config_id, tour_url)
        ).fetchone()

        if existing:
            old_price = existing['last_price']
            result_id = existing['id']
            conn.execute(
                "UPDATE watch_results SET last_price=?, start_date=? WHERE id=?",
                (price_gbp, start_date, result_id)
            )
        else:
            old_price = None
            cur = conn.execute("""
                INSERT INTO watch_results (config_id, tour_name, tour_url, source, start_date, last_price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (config_id, tour_name, tour_url, source, start_date, price_gbp))
            result_id = cur.lastrowid

        conn.execute(
            "INSERT INTO price_history (result_id, price) VALUES (?, ?)",
            (result_id, price_gbp)
        )
        return old_price, result_id


def update_config_check_time(config_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE watch_configs SET last_check=? WHERE id=?",
            (datetime.now().isoformat(), config_id)
        )


# DB'yi başlat
init_db()
