"""
WhatsApp Cloud API sender
Meta Graph API v19.0 üzerinden mesaj gönderir.
"""
import os, requests, logging

log = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com/v19.0"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}",
        "Content-Type": "application/json",
    }


def send_text(to: str, text: str) -> bool:
    """
    Düz metin mesaj gönderir.
    to: uluslararası format, ör: '905321234567' (+ olmadan)
    """
    phone_id = os.getenv("PHONE_NUMBER_ID")
    url = f"{GRAPH_URL}/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text, "preview_url": False},
    }
    try:
        r = requests.post(url, json=payload, headers=_headers(), timeout=15)
        if r.status_code == 200:
            return True
        log.error(f"WA send hata {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        log.error(f"WA send exception: {e}")
        return False


def send_messages(to: str, messages: list[str]) -> None:
    """Birden fazla mesajı sırayla gönderir."""
    for msg in messages:
        # WhatsApp markdown: *bold*, _italic_ — HTML taglarını dönüştür
        clean = _html_to_wa(msg)
        send_text(to, clean)


def _html_to_wa(html: str) -> str:
    """Telegram HTML → WhatsApp markdown."""
    import re
    text = html
    # Bold
    text = re.sub(r'<b>(.*?)</b>', r'*\1*', text, flags=re.DOTALL)
    text = re.sub(r'<strong>(.*?)</strong>', r'*\1*', text, flags=re.DOTALL)
    # Italic
    text = re.sub(r'<i>(.*?)</i>', r'_\1_', text, flags=re.DOTALL)
    text = re.sub(r'<em>(.*?)</em>', r'_\1_', text, flags=re.DOTALL)
    # Code
    text = re.sub(r'<code>(.*?)</code>', r'`\1`', text, flags=re.DOTALL)
    # Links → sadece URL göster
    text = re.sub(r'<a href=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a>', r'\2 → \1', text, flags=re.DOTALL)
    # Kalan HTML taglarını temizle
    text = re.sub(r'<[^>]+>', '', text)
    # HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&#39;', "'")
    return text.strip()
