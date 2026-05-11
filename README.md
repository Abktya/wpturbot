# WpTurBot — WhatsApp Tur Bulucu Bot

WhatsApp üzerinden Türkiye çıkışlı Avrupa tur fiyatlarını karşılaştıran ve aktivite öneren akıllı bot.

## Özellikler

- 🔍 **Tur Fiyatı Araması** — tatilsepeti, jollytur, etstur, setur'dan gerçek zamanlı fiyatlar
- 🎯 **Aktivite Önerileri** — Viator API ile destinasyon bazlı aktiviteler (%8 komisyon)
- 🤖 **Claude AI Router** — Belirsiz mesajları analiz eder, kullanıcıyı doğru komuşa yönlendirir
- 💱 **GBP Dönüşümü** — Tüm TRY/EUR fiyatlar anlık kur ile £'a çevrilir
- ⚡ **Async + Cache** — Paralel scraping, 15 dakika cache, çok kullanıcı desteği

## Desteklenen Destinasyonlar

🇬🇧 Londra · 🇩🇪 Almanya · 🇫🇷 Paris · 🇮🇹 İtalya · 🇪🇸 İspanya  
🇳🇱 Amsterdam · 🇨🇿 Prag · 🇦🇹 Viyana · 🇬🇷 Yunanistan · 🇪🇸 Barselona · 🇮🇹 Roma

## Kullanım

```
londra 700        → £700 altındaki tüm Londra turları
almanya aktivite  → Almanya aktiviteleri (Viator)
paris gezi        → Paris gezilecek yerler
Londra ya gitmek istiyorum  → Claude yönlendirir
```

## Kurulum

```bash
git clone https://github.com/Abktya/wpturbot.git
cd wpturbot
python3 -m venv wpturbot
source wpturbot/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Token ve API keylerini doldur
python app.py
```

## Gerekli Environment Variables

```env
WHATSAPP_TOKEN=...
PHONE_NUMBER_ID=...
WABA_ID=...
WEBHOOK_VERIFY_TOKEN=...
ANTHROPIC_API_KEY=...
VIATOR_API_KEY=...
PORT=8766
CACHE_MINUTES=15
```

## Mimari

```
WhatsApp Mesajı
      ↓
Flask Webhook (app.py)
      ↓
Doğrudan komut mu?
  Evet → Scraper / Viator (hızlı)
  Hayır → Claude Haiku Router
              ↓
        TUR_ARA   → scraper.py (4 site paralel)
        AKTIVITE  → viator.py (Viator API)
        BILGI     → Claude kısa cevap
        KONU_DISI → Kibarca reddet
```

## Teknolojiler

- **Backend:** Python, Flask, aiohttp
- **AI:** Anthropic Claude Haiku 4.5
- **WhatsApp:** Meta Cloud API (Graph API v19)
- **Aktiviteler:** Viator Partner API
- **Scraping:** tatilsepeti, jollytur, etstur, setur (JSON-LD + HTML)
- **Deployment:** systemd + Cloudflare Tunnel

## Lisans

MIT — BKTY Ltd
