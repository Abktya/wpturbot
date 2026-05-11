"""
Viator Affiliate API entegrasyonu.
Destinasyon bazlı aktivite arama, GBP fiyat, puan, affiliate link.
"""

import os, requests, logging
from functools import lru_cache

log = logging.getLogger(__name__)

BASE      = 'https://api.viator.com/partner'
HEADERS   = {
    'Accept-Language': 'en-US',
    'Accept': 'application/json;version=2.0',
    'exp-api-key': os.getenv('VIATOR_API_KEY', ''),
}

# Destinasyon → Viator destination ID
DEST_IDS = {
    'londra':     '737',
    'almanya':    '36',     # Germany
    'paris':      '479',
    'italya':     '21',     # Italy
    'ispanya':    '411',    # Spain
    'amsterdam':  '525',
    'prag':       '591',
    'viyana':     '39',
    'yunanistan': '95',     # Greece / Athens
    'barselona':  '562',
    'roma':       '511',
}


def search_activities(dest_key: str, count: int = 8, sort: str = 'TRAVELER_RATING') -> list[dict]:
    """
    Destinasyon için en iyi aktiviteleri çek.
    sort: TRAVELER_RATING | PRICE_FROM_LOW_TO_HIGH | PRICE_FROM_HIGH_TO_LOW
    """
    dest_id = DEST_IDS.get(dest_key)
    if not dest_id:
        log.warning(f"Viator dest ID bulunamadı: {dest_key}")
        return []

    try:
        r = requests.post(
            f'{BASE}/products/search',
            headers=HEADERS,
            json={
                'filtering': {'destination': dest_id},
                'pagination': {'start': 1, 'count': count},
                'currency': 'GBP',
                'sorting': {'sort': sort, 'order': 'DESCENDING'},
            },
            timeout=15
        )
        r.raise_for_status()
        products = r.json().get('products', [])

        results = []
        for p in products:
            price   = p.get('pricing', {}).get('summary', {}).get('fromPrice', 0)
            rating  = p.get('reviews', {}).get('combinedAverageRating', 0)
            reviews = p.get('reviews', {}).get('totalReviews', 0)
            url     = p.get('productUrl', '')
            # Affiliate parametresi yoksa ekle
            if 'mcid=' not in url:
                url += ('&' if '?' in url else '?') + 'mcid=42383'

            results.append({
                'title':    p.get('title', ''),
                'price':    price,
                'rating':   rating,
                'reviews':  reviews,
                'url':      url,
                'code':     p.get('productCode', ''),
                'duration': _parse_duration(p.get('duration', {})),
            })

        log.info(f"Viator [{dest_key}]: {len(results)} aktivite")
        return results

    except Exception as e:
        log.error(f"Viator API hatası: {e}")
        return []


def _parse_duration(dur: dict) -> str:
    if not dur:
        return ''
    fixed = dur.get('fixedDurationInMinutes')
    if fixed:
        if fixed < 60:
            return f"{fixed} dk"
        elif fixed < 1440:
            return f"{fixed//60} saat"
        else:
            return f"{fixed//1440} gün"
    desc = dur.get('variableDurationFromMinutes')
    if desc:
        return f"{desc//60}+ saat"
    return ''


def format_activities_for_whatsapp(activities: list[dict], dest_label: str) -> str:
    """WhatsApp mesajı formatı."""
    if not activities:
        return f"❌ {dest_label} için aktivite bulunamadı."

    stars = ['🥇','🥈','🥉','4️⃣','5️⃣','6️⃣','7️⃣','8️⃣']
    lines = [f"🎯 *{dest_label} — Aktiviteler & Turlar*\n"]

    for i, a in enumerate(activities):
        emoji = stars[i] if i < len(stars) else f'{i+1}.'
        rating_str = f"⭐{a['rating']:.1f} ({a['reviews']} yorum)" if a['rating'] else ''
        price_str  = f"£{a['price']:.0f}'den" if a['price'] else ''
        dur_str    = f"⏱ {a['duration']}" if a['duration'] else ''

        parts = [x for x in [rating_str, price_str, dur_str] if x]
        meta  = '  •  '.join(parts)

        lines.append(f"{emoji} *{a['title']}*")
        if meta:
            lines.append(meta)
        lines.append(f"🔗 {a['url']}")
        lines.append('')


    return '\n'.join(lines)
