"""
Belirli bir tur URL'sinin güncel fiyatını çeker.
Tatilsepeti ve Jollytur için ayrı parser'lar.
"""

import re, logging
import requests

log = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'tr-TR,tr;q=0.9',
}


def fetch_tatilsepeti_price(url: str) -> tuple[float, str]:
    """
    Tatilsepeti tur sayfasından fiyat çek.
    Dönüş: (price_eur, tour_name)
    """
    try:
        # URL'yi temizle — sadece slug kısmı
        if not url.startswith('http'):
            url = 'https://www.tatilsepeti.com' + url

        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        html = r.text

        # TL fiyatını bul — örn: 36.858,27 TL
        # Büyük fiyat paterni
        # Kişibaşı fiyatı bul — "kisi basi" veya "Kişi başı" context'inde
        # Tatilsepeti fiyat formatı: 36.346,<small>87 TL</small>
        # Kişibaşı context'inde büyük TL fiyatını bul
        tl_matches = re.findall(r'(\d{2,3}\.\d{3}),<small', html)
        # En büyük fiyatı al (taksit değil, gerçek fiyat)
        price_matches = []
        if tl_matches:
            # En düşük fiyat = kişibaşı başlangıç fiyatı
            nums = [int(t.replace('.','')) for t in tl_matches]
            min_val = tl_matches[nums.index(min(nums))]
            price_matches = [min_val]

        # İsim — og:title, JSON-LD veya URL slug'dan
        og_m = re.search(r'og:title"[^>]*content="([^"]+)"', html, re.IGNORECASE)
        ld_m = re.search(r'"@type"\s*:\s*"(?:TouristAttraction|Product|Event)"[^}]+?"name"\s*:\s*"([^"]+)"', html)
        # Slug'dan isim üret (en güvenilir): bir-londra-masali-turu-tr-167650 → Bir Londra Masali Turu
        slug = url.rstrip('/').split('/')[-1].split('?')[0]
        slug = re.sub(r'-tr-\d+$', '', slug)
        name_from_slug = slug.replace('-', ' ').title()

        if ld_m:
            name = ld_m.group(1).strip()
        elif len(name_from_slug) > 5:
            name = name_from_slug
        elif og_m:
            name = og_m.group(1).strip().split('|')[0].strip()
        else:
            name = name_from_slug

        # Döviz kuru (sayfadan)
        eur_m = re.search(r'ttl_exchange_rate_eur = "([^"]+)"', html)
        eur_rate = float(eur_m.group(1)) if eur_m else 52.0

        if price_matches:
            # TL fiyatını EUR'ya çevir
            tl = float(price_matches[0].replace('.', ''))
            eur = round(tl / eur_rate, 0)
            log.info(f"Tatilsepeti fiyat: {tl} TL = {eur} EUR | {name[:50]}")
            return eur, name

        # Alternatif: EUR fiyatını direkt bul
        eur_price_m = re.findall(r'(\d{3,4})\s*€|(\d{3,4})\s*EUR', html)
        if eur_price_m:
            eur = float(eur_price_m[0][0] or eur_price_m[0][1])
            return eur, name

        return 0.0, name

    except Exception as e:
        log.error(f"Tatilsepeti price fetch hatası {url}: {e}")
        return 0.0, ''


def fetch_jollytur_price(url: str) -> tuple[float, str]:
    """
    Jollytur tur sayfasından fiyat çek.
    """
    try:
        if not url.startswith('http'):
            url = 'https://www.jollytur.com' + url

        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        html = r.text

        # EUR fiyat
        eur_m = re.search(r'class="current-price"[^>]*>\s*([\d\.,]+)', html)
        if eur_m:
            eur = float(eur_m.group(1).replace('.', '').replace(',', '.'))
        else:
            eur = 0.0

        # İsim
        name_m = re.search(r'<title>([^<|]+)', html)
        name = name_m.group(1).strip() if name_m else url.split('/')[-1]

        log.info(f"Jollytur fiyat: {eur} EUR | {name[:50]}")
        return eur, name

    except Exception as e:
        log.error(f"Jollytur price fetch hatası {url}: {e}")
        return 0.0, ''


def fetch_etstur_price(url: str) -> tuple[float, str]:
    """Etstur tur fiyatı."""
    try:
        if not url.startswith('http'):
            url = 'https://www.etstur.com' + url

        r = requests.get(url, headers=HEADERS, timeout=20)
        html = r.text

        import json
        jsons = re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.DOTALL)
        for j in jsons:
            try:
                d = json.loads(j)
                price = d.get('offers', {}).get('price')
                name  = d.get('name', '')
                if price:
                    return float(price), name
            except:
                pass

        name_m = re.search(r'<title>([^<|]+)', html)
        name = name_m.group(1).strip() if name_m else ''
        return 0.0, name

    except Exception as e:
        log.error(f"Etstur price fetch hatası: {e}")
        return 0.0, ''


def fetch_price(tour_url: str, source: str) -> tuple[float, str]:
    """Source'a göre doğru fetcher'ı çağır."""
    if source == 'tatilsepeti':
        return fetch_tatilsepeti_price(tour_url)
    elif source == 'jollytur':
        return fetch_jollytur_price(tour_url)
    elif source == 'etstur':
        return fetch_etstur_price(tour_url)
    else:
        return 0.0, ''
