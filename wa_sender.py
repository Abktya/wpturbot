"""
WhatsApp Cloud API sender
Meta Graph API v19.0 üzerinden mesaj gönderir.
"""
import os, re, requests, logging

log = logging.getLogger(__name__)
GRAPH_URL = "https://graph.facebook.com/v19.0"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}",
        "Content-Type": "application/json",
    }


def _post(payload: dict) -> bool:
    phone_id = os.getenv("PHONE_NUMBER_ID")
    try:
        r = requests.post(f"{GRAPH_URL}/{phone_id}/messages",
                          json=payload, headers=_headers(), timeout=15)
        if r.status_code == 200:
            return True
        log.error(f"WA send hata {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        log.error(f"WA send exception: {e}")
        return False


def send_text(to: str, text: str) -> bool:
    return _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text, "preview_url": False},
    })


def send_messages(to: str, messages: list[str]) -> None:
    for msg in messages:
        send_text(to, _html_to_wa(msg))


def send_watch_list(to: str, tours: list[dict], target_gbp: float, dest_key: str) -> bool:
    """
    Interactive List mesajı — her tur için 'Takip Et' seçeneği.
    Kullanıcı tıklayınca button_reply gelir → otomatik takibe alınır.

    tours: [{'name', 'price_gbp', 'url', 'source', 'start_date', ...}]
    max 10 tur gösterilir (WA limiti)
    """
    from scraper import DEST_CONFIG
    cfg   = DEST_CONFIG.get(dest_key, {})
    flag  = cfg.get('flag', '✈️')
    label = cfg.get('label', dest_key)

    rows = []
    for i, t in enumerate(tours[:10]):
        diff     = t['price_gbp'] - target_gbp
        sign     = '+' if diff >= 0 else ''
        price_s  = f"£{t['price_gbp']:.0f}({sign}£{int(abs(diff))})"  # £692(-£8)
        name_s   = t['name'].replace('Turu','').replace('Özel','').strip()
        avail    = 24 - len(price_s) - 1
        title    = f"{price_s} {name_s[:avail]}" if avail > 0 else price_s[:24]

        # Tarih bilgisi
        desc = t.get('start_fmt', '') or t.get('start_date', '')[:7]
        if t.get('nights'):
            desc += f" | {t['nights']}g" if desc else f"{t['nights']} gece"
        desc = desc[:72] if desc else t.get('source', '')

        # Button ID: "watch|source|url|budget"  (max 256 char)
        btn_id = f"watch|{t['source']}|{t['url']}|{target_gbp:.0f}"[:256]

        rows.append({
            "id":          btn_id,
            "title":       title,
            "description": desc,
        })

    if not rows:
        return False

    return _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": f"{flag} {label} — Takip Et"},
            "body": {
                "text": f"£{target_gbp:.0f} aramasındaki turlardan takibe almak istediklerini seç. "
                        f"Fiyat değişince seni haberdar ederim. 🔔"
            },
            "footer": {"text": "Günde 3 kez kontrol edilir (08:00 / 14:00 / 20:00)"},
            "action": {
                "button": "📌 Takip Et",
                "sections": [{
                    "title": "Turlar",
                    "rows":  rows,
                }]
            }
        }
    })


def _html_to_wa(html: str) -> str:
    text = html
    text = re.sub(r'<b>(.*?)</b>',           r'*\1*',    text, flags=re.DOTALL)
    text = re.sub(r'<strong>(.*?)</strong>',  r'*\1*',    text, flags=re.DOTALL)
    text = re.sub(r'<i>(.*?)</i>',            r'_\1_',    text, flags=re.DOTALL)
    text = re.sub(r'<em>(.*?)</em>',          r'_\1_',    text, flags=re.DOTALL)
    text = re.sub(r'<code>(.*?)</code>',      r'`\1`',    text, flags=re.DOTALL)
    text = re.sub(r'<a href=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a>', r'\2 → \1', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;','&').replace('&lt;','<').replace('&gt;','>').replace('&#39;',"'")
    return text.strip()
