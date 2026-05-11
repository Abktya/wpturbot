"""
Watcher — Kriter bazlı tur tarama ve fiyat karşılaştırma.
Her kontrol döngüsünde:
  1. Tüm aktif konfigürasyonları al
  2. Her konfigürasyon için scraper çalıştır
  3. Kriterlere uyan turları filtrele (ay, bütçe, keyword)
  4. Fiyat değişimlerini tespit et
  5. Değişim varsa WhatsApp bildirimi gönder
"""

import logging
from datetime import datetime

log = logging.getLogger(__name__)

MIN_CHANGE_PCT = 2.0   # %2 değişimde bildir


def month_matches(start_date: str, month_num: int | None) -> bool:
    """Tur tarihi belirtilen aydaysa True."""
    if not month_num:
        return True
    if not start_date:
        return False
    try:
        d = datetime.strptime(start_date, '%Y-%m-%d')
        return d.month == month_num
    except:
        return False


def keyword_matches(tour_name: str, keyword: str) -> bool:
    """Tur ismi keyword içeriyorsa True."""
    if not keyword:
        return True
    kw = keyword.lower().strip()
    name = tour_name.lower()
    # Her kelimeyi ayrı kontrol et
    return all(w in name for w in kw.split())


def filter_tours(tours: list[dict], config: dict) -> list[dict]:
    """Konfigürasyona uyan turları filtrele."""
    month_num  = config.get('month_num')
    budget_gbp = config.get('budget_gbp')
    keyword    = config.get('keyword', '')

    result = []
    for t in tours:
        if t.get('price_gbp', 0) <= 0:
            continue
        if budget_gbp and t['price_gbp'] > budget_gbp:
            continue
        if not month_matches(t.get('start_date', ''), month_num):
            continue
        if not keyword_matches(t.get('name', ''), keyword):
            continue
        result.append(t)

    return result


def check_config(config: dict) -> list[dict]:
    """
    Tek bir konfigürasyonu kontrol et.
    Dönüş: değişen turların listesi [{tour, old_price, new_price, change_pct}]
    """
    from scraper import _do_fetch_dest, _cache
    from tracker import upsert_tour_result, update_config_check_time, MONTH_TR_REV
    import asyncio

    config_id  = config['id']
    dest_key   = config['dest_key']
    agent_ph   = config['agent_phone']

    log.info(f"Config #{config_id} kontrol | {dest_key} | ay={config.get('month_num')} | bütçe={config.get('budget_gbp')} | kw={config.get('keyword')}")

    # Scraper — cache'te varsa kullan, yoksa çek
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        all_tours, rates = loop.run_until_complete(_do_fetch_dest(dest_key))
        loop.close()
    except Exception as e:
        log.error(f"Scraper hatası config #{config_id}: {e}")
        return []

    # Kriterlere uyan turları filtrele
    matched = filter_tours(all_tours, config)
    log.info(f"Config #{config_id}: {len(all_tours)} tur → {len(matched)} eşleşti")

    changes = []
    for t in matched:
        old_price, result_id = upsert_tour_result(
            config_id,
            t['name'], t['url'], t['source'],
            t.get('start_date', ''),
            t['price_gbp']
        )

        if old_price is None:
            continue  # İlk kayıt, karşılaştırma yok

        change_pct = abs(t['price_gbp'] - old_price) / old_price * 100 if old_price > 0 else 0

        if change_pct >= MIN_CHANGE_PCT:
            changes.append({
                'tour_name':  t['name'],
                'tour_url':   t['url'],
                'source':     t['source'],
                'start_date': t.get('start_fmt') or t.get('start_date', ''),
                'old_price':  old_price,
                'new_price':  t['price_gbp'],
                'change_pct': change_pct,
                'price_eur':  t.get('price_eur', 0),
            })

    update_config_check_time(config_id)
    return changes


def build_change_message(config: dict, changes: list[dict]) -> str:
    """Değişim bildirimi mesajı oluştur."""
    from tracker import MONTH_TR_REV
    from scraper import DEST_CONFIG

    cfg      = DEST_CONFIG.get(config['dest_key'], {})
    flag     = cfg.get('flag', '✈️')
    label    = cfg.get('label', config['dest_key'])
    month_n  = config.get('month_num')
    month_s  = MONTH_TR_REV.get(month_n, '') if month_n else ''
    budget_s = f"£{config['budget_gbp']:.0f}" if config.get('budget_gbp') else ''

    header = f"🔔 *Fiyat Değişimi — {flag} {label}*"
    if month_s or budget_s:
        header += f" ({' | '.join(filter(None,[month_s,budget_s]))})\n"
    else:
        header += "\n"

    lines = [header]
    for c in changes[:5]:  # Max 5 tur
        diff = c['new_price'] - c['old_price']
        icon = '📉' if diff < 0 else '📈'
        sign = '+' if diff > 0 else ''

        lines.append(
            f"\n{icon} *{c['tour_name'][:50]}*\n"
            f"   💰 £{c['old_price']:.0f} → *£{c['new_price']:.0f}* ({sign}£{diff:.0f} | {c['change_pct']:.1f}%)\n"
            f"   📅 {c['start_date']}\n"
            f"   🌐 {c['source']}\n"
            f"   🔗 {c['tour_url']}"
        )

    if len(changes) > 5:
        lines.append(f"\n_...ve {len(changes)-5} tur daha_")

    return '\n'.join(lines)


def run_all_checks():
    """Tüm aktif konfigürasyonları kontrol et — scheduler'dan çağrılır."""
    from tracker import get_all_active_configs
    from wa_sender import send_text

    configs = get_all_active_configs()
    if not configs:
        return

    log.info(f"=== Fiyat kontrolü başladı — {len(configs)} aktif takip | {datetime.now().strftime('%H:%M')} ===")

    for config in configs:
        try:
            changes = check_config(config)
            if changes:
                msg = build_change_message(config, changes)
                send_text(config['agent_phone'], msg)
                log.info(f"Bildirim → {config['agent_phone']} | {len(changes)} değişim")
        except Exception as e:
            log.error(f"Config #{config['id']} hata: {e}")

    log.info(f"=== Fiyat kontrolü tamamlandı ===")
