"""
Fiyat Takip Scheduler — APScheduler
Her 6 saatte bir tüm aktif takipleri kontrol eder.
Fiyat değişiminde WhatsApp bildirimi gönderir.
"""

import logging, os
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger(__name__)

# Bildirim eşiği — minimum değişim oranı
MIN_CHANGE_PCT = float(os.getenv('PRICE_ALERT_PCT', '3'))  # %3


def check_all_prices():
    """Tüm aktif takipleri kontrol et, değişim varsa bildir."""
    from tracker import get_all_active_watches, update_price
    from price_checker import fetch_price
    from wa_sender import send_text

    watches = get_all_active_watches()
    if not watches:
        return

    log.info(f"Fiyat kontrolü başladı — {len(watches)} takip")

    for w in watches:
        try:
            new_price, _ = fetch_price(w['tour_url'], w['source'])
            if new_price <= 0:
                continue

            old_price = w['last_price'] or 0
            update_price(w['id'], new_price)

            if old_price <= 0:
                continue  # İlk kayıt, karşılaştırma yok

            change = new_price - old_price
            change_pct = abs(change / old_price * 100)

            if change_pct < MIN_CHANGE_PCT:
                continue  # Küçük değişim, bildirim gönderme

            # GBP dönüşümü için kuru al
            from scraper import _rates_store
            eur_gbp = _rates_store.get('EUR_GBP', 0.866)
            old_gbp = round(old_price * eur_gbp)
            new_gbp = round(new_price * eur_gbp)
            diff_gbp = new_gbp - old_gbp

            if change < 0:
                icon = '📉'
                direction = f"*DÜŞTÜ* ↓ £{abs(diff_gbp)}"
            else:
                icon = '📈'
                direction = f"*ARTTI* ↑ £{abs(diff_gbp)}"

            msg = (
                f"{icon} *Fiyat Değişimi — {w['tour_name'][:50]}*\n\n"
                f"💰 Eski: £{old_gbp} ({old_price:.0f}€)\n"
                f"💰 Yeni: £{new_gbp} ({new_price:.0f}€)\n"
                f"📊 {direction} ({change_pct:.1f}%)\n\n"
                f"🌐 {w['source']}\n"
                f"🔗 {w['tour_url']}"
            )

            send_text(w['agent_phone'], msg)
            log.info(f"Bildirim gönderildi → {w['agent_phone']} | {w['tour_name'][:40]} | {change_pct:.1f}%")

        except Exception as e:
            log.error(f"Watch {w['id']} kontrol hatası: {e}")

    log.info("Fiyat kontrolü tamamlandı")


def start_scheduler():
    """Scheduler'ı başlat — her 6 saatte bir çalışır."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        check_all_prices,
        trigger=IntervalTrigger(hours=6),
        id='price_check',
        name='Fiyat Kontrolü',
        replace_existing=True,
        next_run_time=None  # Hemen çalıştırma, ilk 6 saatte çalışsın
    )
    scheduler.start()
    log.info("Fiyat takip scheduler başlatıldı ✓ (her 6 saatte bir)")
    return scheduler
