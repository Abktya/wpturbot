"""
Scheduler — Günde 3 kez fiyat kontrolü
08:00, 14:00, 20:00 BST
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)


def run_check():
    """Kontrol döngüsünü başlat."""
    from watcher import run_all_checks
    try:
        run_all_checks()
    except Exception as e:
        log.error(f"Scheduler check hatası: {e}")


def start_scheduler():
    scheduler = BackgroundScheduler(timezone='Europe/London')

    # Günde 3 kez: 08:00, 14:00, 20:00
    for hour in [8, 14, 20]:
        scheduler.add_job(
            run_check,
            trigger=CronTrigger(hour=hour, minute=0),
            id=f'price_check_{hour}',
            name=f'Fiyat Kontrolü {hour:02d}:00',
            replace_existing=True,
        )

    scheduler.start()
    log.info("Scheduler başlatıldı ✓ — 08:00, 14:00, 20:00 (Londra saati)")
    return scheduler
