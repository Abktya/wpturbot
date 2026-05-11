"""
Claude API Router — Akıllı Yönlendirici
Claude burada sohbet botu DEĞİL, intent analizi + yönlendirme yapar.
"""

import os, json, re, requests, logging

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')

from scraper import DEST_CONFIG
DEST_LIST = ', '.join(DEST_CONFIG.keys())

SYSTEM_PROMPT = f"""Sen bir tur ve seyahat asistanısın. Kullanıcı mesajlarını analiz edip JSON formatında yanıt verirsin.

Yapabildiğin şeyler:
1. Türkiye çıkışlı Avrupa turlarının fiyatlarını arama
2. Destinasyonlardaki aktivite ve gezileri listeleme
3. Kısa seyahat bilgisi verme (vize, ulaşım, para birimi)

Desteklenen destinasyonlar: {DEST_LIST}

SADECE şu JSON formatında yanıt ver, kesinlikle başka şey yazma:
{{"action": "TUR_ARA", "dest_key": "londra", "budget": 700, "message": "kisa mesaj"}}

action değerleri:
- TUR_ARA: tur fiyatı sorusu. budget sayı olmalı (belirsizse null), dest_key belirsizse null
- AKTIVITE: gezilecek yer, aktivite sorusu. dest_key zorunlu
- BILGI: vize/ulaşım/para sorusu. message kısa cevap + sisteme yönlendirme içermeli
- KONU_DISI: seyahatle alakasız. message sadece yapabileceklerini anlat

Mesajlar Türkçe, max 200 karakter, *bold* WhatsApp formatında."""


def analyze_intent(user_message: str) -> dict:
    """Kullanıcı mesajını analiz et, action + parametreler döndür."""
    fallback = {
        'action': 'KONU_DISI', 'dest_key': None, 'budget': None,
        'message': 'Anlayamadım.\n*Tur ara:* londra 700\n*Aktivite:* londra aktivite'
    }
    try:
        r = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            json={
                'model': 'claude-haiku-4-5-20251001',
                'max_tokens': 250,
                'system': SYSTEM_PROMPT,
                'messages': [{'role': 'user', 'content': user_message}]
            },
            timeout=10
        )
        r.raise_for_status()
        raw = r.json()['content'][0]['text'].strip()

        # JSON temizle — ```json...``` veya düz { } bloğu
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if m:
            raw = m.group(1)
        else:
            m2 = re.search(r'(\{[^{}]+\})', raw, re.DOTALL)
            if m2:
                raw = m2.group(1)

        result = json.loads(raw)

        # budget string ise float'a çevir
        if result.get('budget') and not isinstance(result['budget'], (int, float)):
            try:
                result['budget'] = float(str(result['budget']).replace(',','.').replace('£',''))
            except:
                result['budget'] = None

        # Eksik alanları varsayılanla doldur
        result.setdefault('action', 'KONU_DISI')
        result.setdefault('dest_key', None)
        result.setdefault('budget', None)
        result.setdefault('message', '')
        log.info(f"Claude: action={result.get('action')} dest={result.get('dest_key')} budget={result.get('budget')}")
        return result

    except Exception as e:
        log.error(f"Claude router hatası: {e}")
        return fallback
