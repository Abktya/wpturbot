"""
WhatsApp Cloud API Webhook — Flask uygulaması
Mesaj akışı:
  1. Doğrudan komut tanıma (hızlı, API çağrısı yok)
  2. Belirsiz mesajlar → Claude Router (intent analizi)
  3. Claude kararına göre: tur ara / aktivite getir / bilgi ver / yönlendir
"""

import os, asyncio, logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
logging.basicConfig(format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)
app = Flask(__name__)

VERIFY_TOKEN = os.getenv('WEBHOOK_VERIFY_TOKEN', 'wpturbot_verify_2024')

# ─── Aktivite anahtar kelimeleri ───
AKTIVITE_KW = ['aktivite','aktiviteler','gezi','gezilecek','yapilacak','yapılacak',
               'activity','activities','things to do','ne yapilir','ne yapılır',
               'ne gezilir','geziler','görülecek','gorulebilecek']

# ─── Yardım anahtar kelimeleri ───
YARDIM_KW = ['merhaba','selam','hi','hello','start','/start','yardim','yardım','help','neler yapabilirsin']


@app.get('/webhook')
def verify():
    mode, token, challenge = (request.args.get(k) for k in ('hub.mode','hub.verify_token','hub.challenge'))
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        log.info("Webhook doğrulandı ✓")
        return challenge, 200
    return 'Forbidden', 403


def _parse_direct(text: str):
    """
    Açık komutları hızlıca tanı. Belirsizse (None, None) döndür.
    """
    from scraper import resolve_dest
    parts = text.strip().lower().split()

    # Fiyat + destinasyon kombinasyonu
    if len(parts) >= 2:
        d = resolve_dest(parts[0])
        try:
            p = float(parts[1].replace('£','').replace(',','.'))
            if d and 10 <= p <= 50000:
                return ('TUR_ARA', d, p)
        except ValueError:
            pass
        d2 = resolve_dest(parts[1])
        try:
            p2 = float(parts[0].replace('£','').replace(',','.'))
            if d2 and 10 <= p2 <= 50000:
                return ('TUR_ARA', d2, p2)
        except ValueError:
            pass

    # Sadece sayı → londra varsayılan
    if len(parts) == 1:
        try:
            p = float(parts[0].replace('£','').replace(',','.'))
            if 10 <= p <= 50000:
                return ('TUR_ARA', 'londra', p)
        except ValueError:
            pass

    # Aktivite keyword
    if any(kw in text.lower() for kw in AKTIVITE_KW):
        from scraper import resolve_dest
        dest = next((resolve_dest(w) for w in parts if resolve_dest(w)), 'londra')
        return ('AKTIVITE', dest, None)

    # Yardım
    if any(kw in text.lower() for kw in YARDIM_KW):
        return ('YARDIM', None, None)

    return (None, None, None)


async def _handle_async(sender: str, text: str):
    from scraper import find_tours_below, DEST_CONFIG
    from formatter import format_results
    from viator import search_activities, format_activities_for_whatsapp
    from wa_sender import send_messages, send_text

    # 1. Doğrudan komut dene
    action, dest_key, budget = _parse_direct(text)

    # 2. Belirsizse Claude'a yönlendir
    if action is None:
        from claude_router import analyze_intent
        result = analyze_intent(text)
        action   = result.get('action', 'KONU_DISI')
        dest_key = result.get('dest_key')
        budget   = result.get('budget')
        cl_msg   = result.get('message', '')

        # Claude'un mesajını kullanıcıya göster
        if cl_msg:
            send_text(sender, cl_msg)

        # Claude bütçe veya dest bilgisi döndürmediyse dur
        if action == 'TUR_ARA' and (not dest_key or not budget):
            return
        if action == 'AKTIVITE' and not dest_key:
            return
        if action in ('BILGI', 'KONU_DISI'):
            return  # Claude mesajı zaten gönderildi

    # 3. Aksiyonu çalıştır
    if action == 'YARDIM':
        dest_list = '\n'.join(f"  {v['flag']} {k}" for k, v in DEST_CONFIG.items())
        send_text(sender,
            "✈️ *Tur Bulucu Bot*\n\n"
            "*Tur fiyatı ara:*\n"
            "  londra 560\n"
            "  almanya 799\n"
            "  paris 650\n\n"
            "*Aktivite & gezi bul:*\n"
            "  londra aktivite\n"
            "  paris gezi\n\n"
            f"Destinasyonlar:\n{dest_list}\n\n"
            "Fiyat £ cinsindendir (kişi başı)."
        )
        return

    if action == 'AKTIVITE':
        cfg = DEST_CONFIG.get(dest_key, DEST_CONFIG['londra'])
        send_text(sender, f"{cfg['flag']} *{cfg['label']}* aktiviteleri aranıyor...")
        activities = search_activities(dest_key, count=8)
        msg = format_activities_for_whatsapp(activities, cfg['label'])
        send_text(sender, msg)
        return

    if action == 'TUR_ARA':
        cfg = DEST_CONFIG.get(dest_key, DEST_CONFIG['londra'])
        send_text(sender, f"{cfg['flag']} *{cfg['label']}* — £{budget:.0f} ve altı turlar aranıyor...")
        try:
            tours, rates = await find_tours_below(float(budget), dest_key)
            if not tours:
                send_text(sender,
                    f"❌ £{budget:.0f} altında *{cfg['label']}* turu bulunamadı.\n"
                    f"Daha yüksek bütçe dene: *{dest_key} {int(float(budget)*1.3)}*"
                )
                return
            if len(tours) <= 5:
                send_text(sender,
                    f"ℹ️ £{budget:.0f} altında *{len(tours)} tur* bulundu.\n"
                    f"Daha fazla için: *{dest_key} {int(float(budget)*1.2)}*"
                )
            messages = format_results(tours, float(budget), rates, dest_key)
            send_messages(sender, messages)
        except Exception as e:
            log.exception(f"Tur arama hatası: {e}")
            send_text(sender, f"❌ Hata oluştu: {str(e)[:150]}")


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@app.post('/webhook')
def webhook():
    data = request.get_json(silent=True) or {}
    try:
        msg = data.get('entry',[{}])[0].get('changes',[{}])[0].get('value',{}).get('messages',[])
        if not msg:
            return jsonify({'status': 'no_message'}), 200
        m = msg[0]
        if m.get('type') == 'text':
            text = m.get('text',{}).get('body','').strip()
            sender = m.get('from','')
            if text:
                log.info(f"Gelen | {sender}: {text[:80]}")
                _run_async(_handle_async(sender, text))
    except Exception as e:
        log.exception(f"Webhook hatası: {e}")
    return jsonify({'status': 'ok'}), 200


@app.get('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'wpturbot'}), 200


if __name__ == '__main__':
    port = int(os.getenv('PORT', 8766))
    log.info(f"wpturbot başlatılıyor port={port}")
    app.run(host='0.0.0.0', port=port, debug=False)
