"""
Async multi-destination scraper
Desteklenen siteler: tatilsepeti, jollytur, etstur, setur (sadece londra)
Cache key: "{dest}_{target_gbp}" — concurrent user safe
"""

import asyncio, re, json, logging, time
from datetime import datetime
from html import unescape
import aiohttp

log = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'tr-TR,tr;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=20)
CACHE_TTL     = 15 * 60

MONTH_TR = {
    'Ocak':'01','Şubat':'02','Mart':'03','Nisan':'04','Mayıs':'05','Haziran':'06',
    'Temmuz':'07','Ağustos':'08','Eylül':'09','Ekim':'10','Kasım':'11','Aralık':'12',
}

# ─────────────────────────────────────────────────────────────
# DESTINASYON KONFİGÜRASYONU
# ─────────────────────────────────────────────────────────────

DEST_CONFIG = {
    'londra': {
        'flag': '🇬🇧', 'label': 'Londra / İngiltere',
        'aliases': ['ingiltere','london','uk','england','britanya'],
        'tatilsepeti': ['londra-turlari','ingiltere-turlari'],
        'jollytur':    ['londra-turlari','ingiltere-turlari'],
        'etstur':      ['Londra-Turlari','Ingiltere-Turlari'],
        'setur':       ['tum-turlar-dahil-yurt-disi-turlari?region=4249'],
    },
    'almanya': {
        'flag': '🇩🇪', 'label': 'Almanya',
        'aliases': ['germany','deutschland','berlin','münchen','frankfurt'],
        'tatilsepeti': ['almanya-turlari'],
        'jollytur':    ['almanya-turlari'],
        'etstur':      ['Almanya-Turlari','Berlin-Turlari'],
        'setur':       [],
    },
    'paris': {
        'flag': '🇫🇷', 'label': 'Paris / Fransa',
        'aliases': ['fransa','france'],
        'tatilsepeti': ['paris-turlari'],
        'jollytur':    ['paris-turlari'],
        'etstur':      ['Paris-Turlari'],
        'setur':       [],
    },
    'italya': {
        'flag': '🇮🇹', 'label': 'İtalya',
        'aliases': ['italy','rome','roma','venedik','floransa','milan'],
        'tatilsepeti': ['italya-turlari','roma-turlari'],
        'jollytur':    ['italya-turlari'],
        'etstur':      ['Roma-Turlari'],
        'setur':       [],
    },
    'ispanya': {
        'flag': '🇪🇸', 'label': 'İspanya',
        'aliases': ['spain','barselona','madrid','barcelona'],
        'tatilsepeti': ['ispanya-turlari'],
        'jollytur':    ['ispanya-turlari'],
        'etstur':      ['Ispanya-Turlari','Barselona-Turlari'],
        'setur':       [],
    },
    'amsterdam': {
        'flag': '🇳🇱', 'label': 'Amsterdam / Hollanda',
        'aliases': ['hollanda','netherlands','holland'],
        'tatilsepeti': ['amsterdam-turlari'],
        'jollytur':    ['amsterdam-turlari'],
        'etstur':      ['Amsterdam-Turlari'],
        'setur':       [],
    },
    'prag': {
        'flag': '🇨🇿', 'label': 'Prag / Çekya',
        'aliases': ['çekya','czech','prague','cekya'],
        'tatilsepeti': ['prag-turlari'],
        'jollytur':    ['prag-turlari'],
        'etstur':      ['Prag-Turlari'],
        'setur':       [],
    },
    'viyana': {
        'flag': '🇦🇹', 'label': 'Viyana / Avusturya',
        'aliases': ['avusturya','austria','vienna'],
        'tatilsepeti': ['viyana-turlari'],
        'jollytur':    ['viyana-turlari'],
        'etstur':      ['Viyana-Turlari'],
        'setur':       [],
    },
    'yunanistan': {
        'flag': '🇬🇷', 'label': 'Yunanistan',
        'aliases': ['greece','atina','athens','selanik'],
        'tatilsepeti': ['yunanistan-turlari'],
        'jollytur':    ['yunanistan-turlari'],
        'etstur':      [],
        'setur':       [],
    },
    'barselona': {
        'flag': '🇪🇸', 'label': 'Barselona',
        'aliases': ['barcelona'],
        'tatilsepeti': ['barselona-turlari'],
        'jollytur':    ['barselona-turlari'],
        'etstur':      ['Barselona-Turlari'],
        'setur':       [],
    },
    'roma': {
        'flag': '🇮🇹', 'label': 'Roma',
        'aliases': ['rome'],
        'tatilsepeti': ['roma-turlari'],
        'jollytur':    ['roma-turlari'],
        'etstur':      ['Roma-Turlari'],
        'setur':       [],
    },
}

# Alias → dest key lookup
_ALIAS_MAP: dict[str, str] = {}
for _k, _v in DEST_CONFIG.items():
    _ALIAS_MAP[_k] = _k
    for _a in _v['aliases']:
        _ALIAS_MAP[_a.lower()] = _k


def resolve_dest(raw: str) -> str | None:
    """Kullanıcı girdisini dest key'e çevirir. Bulamazsa None döner."""
    return _ALIAS_MAP.get(raw.lower().strip())


# ─────────────────────────────────────────────────────────────
# CACHE + PER-KEY LOCK
# ─────────────────────────────────────────────────────────────

class SearchCache:
    def __init__(self, ttl: int = CACHE_TTL):
        self._ttl   = ttl
        self._store: dict[str, dict]         = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta  = asyncio.Lock()

    async def _lock(self, key: str) -> asyncio.Lock:
        async with self._meta:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    def _hit(self, key: str):
        e = self._store.get(key)
        if e and (time.time() - e['ts']) < self._ttl:
            return e['tours'], e['rates']
        return None, None

    def _set(self, key: str, tours, rates):
        self._store[key] = {'ts': time.time(), 'tours': tours, 'rates': rates}

    async def get_or_fetch(self, key: str, fn) -> tuple[list, dict]:
        t, r = self._hit(key)
        if t is not None:
            log.info(f"Cache HIT {key}")
            return t, r
        lock = await self._lock(key)
        async with lock:
            t, r = self._hit(key)
            if t is not None:
                return t, r
            log.info(f"Cache MISS {key} — scraping")
            t, r = await fn()
            self._set(key, t, r)
            return t, r

_cache = SearchCache()


# ─────────────────────────────────────────────────────────────
# DÖVİZ KURU
# ─────────────────────────────────────────────────────────────

_rates_store: dict = {}
_rates_ts: float = 0.0

async def get_exchange_rates(session: aiohttp.ClientSession) -> dict:
    global _rates_store, _rates_ts
    if _rates_store and (time.time() - _rates_ts) < 3600:
        return _rates_store
    try:
        async with session.get('https://open.er-api.com/v6/latest/GBP',
                               timeout=aiohttp.ClientTimeout(total=10)) as resp:
            r = (await resp.json(content_type=None))['rates']
            _rates_store = {'GBP_TRY': r.get('TRY',61.0), 'GBP_EUR': r.get('EUR',1.155),
                            'EUR_GBP': 1/r.get('EUR',1.155)}
            _rates_ts = time.time()
            log.info(f"Kur: 1£={_rates_store['GBP_TRY']:.2f}₺")
            return _rates_store
    except Exception as e:
        log.warning(f"Kur hatası: {e}")
        return _rates_store or {'GBP_TRY':61.0,'GBP_EUR':1.155,'EUR_GBP':0.866}


# ─────────────────────────────────────────────────────────────
# PARSE FONKSİYONLARI (site-spesifik, URL-bağımsız)
# ─────────────────────────────────────────────────────────────

def _parse_tatilsepeti(html: str) -> list[dict]:
    links = []
    seen_s: set = set()
    for m in re.finditer(r'href="(/[^"]*-tr-\d+(?:\?[^"]*)?)"', html):
        s = m.group(1).split('?')[0]
        if s not in seen_s:
            seen_s.add(s); links.append(s)

    items = []
    for j in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            d = json.loads(j)
            if d.get('@type') == 'ItemList':
                items = d.get('itemListElement', []); break
        except: pass

    tours = []
    for i, li in enumerate(items):
        tour = li.get('item', {}); event = li.get('subjectOf', {})
        name = tour.get('name','').strip()
        if not name: continue
        try: price_eur = float(str(tour.get('offers',{}).get('price','0')).replace(',','.'))
        except: price_eur = 0.0
        sd = event.get('startDate',''); ed = event.get('endDate','')
        nights, sfmt, efmt = 0, '', ''
        if sd and ed:
            try:
                d1=datetime.strptime(sd,'%Y-%m-%d'); d2=datetime.strptime(ed,'%Y-%m-%d')
                nights=(d2-d1).days; sfmt=d1.strftime('%d %b %Y'); efmt=d2.strftime('%d %b %Y')
            except: pass
        tours.append({'name':name,'price_eur':price_eur,'description':tour.get('description','').strip(),
            'start_date':sd,'end_date':ed,'start_fmt':sfmt,'end_fmt':efmt,'nights':nights,
            'image':tour.get('image',''),'url':('https://www.tatilsepeti.com'+links[i]) if i<len(links) else '',
            'source':'tatilsepeti'})
    return tours


def _parse_jollytur(html: str) -> list[dict]:
    tours, seen = [], set()
    for b in re.split(r'(?=<div[^>]*class="list"[^>]*data-url=")', html):
        url_m = re.search(r'data-url="(/[^"]+)"', b)
        if not url_m: continue
        slug = url_m.group(1)
        if slug in seen: continue
        seen.add(slug)
        nm = (re.search(r'title="([^"]+)"[^>]*class="tourName',b) or
              re.search(r'class="tourName[^"]*"[^>]*title="([^"]+)"',b))
        name = unescape(nm.group(1)).strip() if nm else ''
        if not name: continue
        em = re.search(r'class="current-price"[^>]*>\s*([\d\.,]+)',b)
        if not em: continue
        try: price_eur = float(em.group(1).replace('.','').replace(',','.'))
        except: price_eur = 0.0
        nm2 = re.search(r'(\d+)\s*Gece', name+b, re.IGNORECASE)
        nights = int(nm2.group(1)) if nm2 else 0
        dm = re.search(r'(\d{1,2})\s*(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s*(\d{4})',b,re.IGNORECASE)
        sd,sfmt='',''
        if dm:
            mon=MONTH_TR.get(dm.group(2).capitalize(),'00')
            sd=f"{dm.group(3)}-{mon}-{dm.group(1).zfill(2)}"; sfmt=f"{dm.group(1)} {dm.group(2)} {dm.group(3)}"
        tours.append({'name':name,'price_eur':price_eur,'description':'','start_date':sd,'end_date':'',
            'start_fmt':sfmt,'end_fmt':'','nights':nights,'image':'',
            'url':'https://www.jollytur.com'+slug,'source':'jollytur'})
    return tours


def _parse_etstur(html: str) -> list[dict]:
    slugs, seen_s = [], set()
    for m in re.finditer(r'href="(/Yurtdisi-Tatil-Turlari/[a-z0-9\-]+-JTS\w+)"', html):
        s=m.group(1)
        if s not in seen_s: seen_s.add(s); slugs.append(s)
    items = []
    for j in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            d=json.loads(j)
            if d.get('@type')=='ItemList': items=d.get('itemListElement',[]); break
        except: pass
    tours = []
    for i, li in enumerate(items):
        t=li.get('item',{}); name=t.get('name','').strip()
        if not name: continue
        offers=t.get('offers',{})
        if isinstance(offers,dict) and offers.get('priceCurrency')=='USD': continue
        try: price_eur=float(str(offers.get('price','0')).replace(',','.'))
        except: price_eur=0.0
        gece=re.search(r'(\d+)\s*Gece',name,re.IGNORECASE)
        url=('https://www.etstur.com'+slugs[i]) if i<len(slugs) else t.get('url','')
        tours.append({'name':name,'price_eur':price_eur,'description':t.get('description','').strip(),
            'start_date':'','end_date':'','start_fmt':'','end_fmt':'',
            'nights':int(gece.group(1)) if gece else 0,'image':t.get('image',''),
            'url':url,'source':'etstur'})
    return tours


def _parse_setur(html: str, dest_key: str) -> list[dict]:
    cfg   = DEST_CONFIG[dest_key]
    # Setur için slug filtresi — destinasyona ait anahtar kelimeler
    kw = [dest_key] + cfg['aliases'][:3]
    tours, seen = [], set()
    cards = re.split(r'(?=<div[^>]*class="sc-30ab29ee-0[^"]*")', html)
    for c in cards[1:]:
        slug_m = re.search(r'href="(/[a-z0-9\-]{10,80})"', c)
        if not slug_m: continue
        slug = slug_m.group(1)
        if any(x in slug for x in ['otel','hotel','transfer']): continue
        if slug in seen: continue
        seen.add(slug)
        title_m = re.search(r'title="([^"]+)"', c)
        name = unescape(title_m.group(1)).strip() if title_m else ''
        if not name: continue
        eur_m = re.search(r'([\d]{1,2}\.[\d]{3}|[\d]{3,4})\s*€', c)
        try: price_eur = float((eur_m.group(1) if eur_m else '0').replace('.',''))
        except: price_eur = 0.0
        if price_eur == 0: continue
        gece_m = re.search(r'(\d+)\s*Gece', c, re.IGNORECASE)
        nights = int(gece_m.group(1)) if gece_m else 0
        dm = re.search(r'(\d{1,2})\s*(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s*(\d{4})',c,re.IGNORECASE)
        sd,sfmt='',''
        if dm:
            mon=MONTH_TR.get(dm.group(2).capitalize(),'00')
            sd=f"{dm.group(3)}-{mon}-{dm.group(1).zfill(2)}"; sfmt=f"{dm.group(1)} {dm.group(2)} {dm.group(3)}"
        tours.append({'name':name,'price_eur':price_eur,'description':'','start_date':sd,'end_date':'',
            'start_fmt':sfmt,'end_fmt':'','nights':nights,'image':'',
            'url':'https://www.setur.com.tr'+slug,'source':'setur'})
    return tours


# ─────────────────────────────────────────────────────────────
# GENEL FETCHER — URL listesi + parse fonksiyonu
# ─────────────────────────────────────────────────────────────

async def _fetch_pages(session, urls: list[str], parse_fn, source: str,
                       batch_size: int = 2) -> list[dict]:
    all_tours, seen = [], set()

    async def _get(url: str) -> list[dict]:
        try:
            async with session.get(url, timeout=FETCH_TIMEOUT) as resp:
                resp.raise_for_status()
                html = await resp.text(encoding='utf-8', errors='replace')
                return parse_fn(html)
        except Exception as e:
            log.error(f"{source} {url.split('/')[-1][:40]}: {type(e).__name__}")
            return []

    for i in range(0, len(urls), batch_size):
        batch = urls[i:i+batch_size]
        results = await asyncio.gather(*[_get(u) for u in batch])
        got = 0
        for tours in results:
            for t in tours:
                k = f"{t['name']}_{t['start_date']}"
                if k not in seen:
                    seen.add(k); all_tours.append(t); got += 1
        if got == 0 and i > 0:
            break   # boş sayfa → dur
        if i + batch_size < len(urls):
            await asyncio.sleep(0.3)

    log.info(f"{source}: {len(all_tours)} tur")
    return all_tours


def _build_urls(dest_key: str) -> dict[str, list[str]]:
    """Destinasyon config'inden site URL listelerini oluştur."""
    cfg = DEST_CONFIG[dest_key]
    base = {
        'tatilsepeti': [f"https://www.tatilsepeti.com/{s}" for s in cfg['tatilsepeti']],
        'jollytur':    [f"https://www.jollytur.com/{s}"    for s in cfg['jollytur']],
        'etstur':      [f"https://www.etstur.com/Yurtdisi-Tatil-Turlari/{s}" for s in cfg['etstur']],
        'setur':       [f"https://www.setur.com.tr/{s}"   for s in cfg['setur']],
    }
    # tatilsepeti için sayfa 2 ekle
    ts2 = [u+'?sayfa=2' for u in base['tatilsepeti']]
    base['tatilsepeti'] += ts2
    return base


# ─────────────────────────────────────────────────────────────
# ANA FETCH
# ─────────────────────────────────────────────────────────────

async def _do_fetch_dest(dest_key: str) -> tuple[list[dict], dict]:
    urls = _build_urls(dest_key)
    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        rates, ts, jt, et, st = await asyncio.gather(
            get_exchange_rates(session),
            _fetch_pages(session, urls['tatilsepeti'], _parse_tatilsepeti,  'Tatilsepeti'),
            _fetch_pages(session, urls['jollytur'],    _parse_jollytur,      'Jollytur'),
            _fetch_pages(session, urls['etstur'],      _parse_etstur,        'Etstur'),
            _fetch_pages(session, urls['setur'],
                         lambda h: _parse_setur(h, dest_key), 'Setur'),
        )

    eur_gbp = rates['EUR_GBP']
    seen, unique = set(), []
    for t in (ts or []) + (jt or []) + (et or []) + (st or []):
        k = f"{t['source']}_{t['name']}_{t['start_date']}"
        if k not in seen:
            seen.add(k)
            t['price_gbp'] = round(t['price_eur'] * eur_gbp, 0) if t['price_eur'] > 0 else 0.0
            unique.append(t)

    log.info(f"[{dest_key}] Toplam: {len(unique)} tur (ts:{len(ts)} jt:{len(jt)} et:{len(et)} st:{len(st)})")
    return unique, rates


# ─────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────

async def find_tours_below(target_gbp: float, dest_key: str = 'londra') -> tuple[list[dict], dict]:
    """
    Hedef fiyatın altındaki tüm turları döndürür.
    Cache key: "{dest}_{target}" — concurrent safe.
    """
    cache_key = f"{dest_key}_{target_gbp}"
    all_tours, rates = await _cache.get_or_fetch(
        cache_key,
        lambda: _do_fetch_dest(dest_key)
    )
    valid  = [t for t in all_tours if 0 < t['price_gbp'] <= target_gbp]
    ranked = sorted(valid, key=lambda t: t['price_gbp'], reverse=True)
    return ranked, rates
