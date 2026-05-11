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
from scheduler import start_scheduler

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
logging.basicConfig(format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)
app = Flask(__name__)

# Fiyat takip scheduler'ı başlat
_scheduler = start_scheduler()

VERIFY_TOKEN = os.getenv('WEBHOOK_VERIFY_TOKEN', 'wpturbot_verify_2024')

# ─── Aktivite anahtar kelimeleri ───
AKTIVITE_KW = ['aktivite','aktiviteler','gezi','gezilecek','yapilacak','yapılacak',
               'activity','activities','things to do','ne yapilir','ne yapılır',
               'ne gezilir','geziler','görülecek','gorulebilecek']

# ─── Yardım anahtar kelimeleri ───
YARDIM_KW = ['merhaba','selam','hi','hello','start','/start','yardim','yardım','help','neler yapabilirsin']
TAKIP_KW = ['takip et','takibe al','takip ekle','takip:','watch']
TAKIPLER_KW = ['takipler','takip listesi','takiplerimi göster','watches']
TAKIP_SIL_KW = ['takip sil','takibi sil','takipten çıkar','unwatch']


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

    # Takip komutları
    tl = text.lower()
    if any(kw in tl for kw in TAKIP_SIL_KW):
        return ('TAKIP_SIL', None, None)
    if any(kw in tl for kw in TAKIPLER_KW):
        return ('TAKIPLER', None, None)
    if any(kw in tl for kw in TAKIP_KW):
        return ('TAKIP_EKLE', None, None)

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
    # ── TAKİP EKLE ──────────────────────────────────────
    if action == 'TAKIP_EKLE':
        from claude_router import parse_watch_command
        from tracker import add_watch_config, MONTH_TR_REV
        from scraper import DEST_CONFIG

        send_text(sender, "⏳ Takip kriterleri analiz ediliyor...")

        # Komutu parse et
        parsed = parse_watch_command(text)
        dest_key   = parsed.get('dest_key')
        month_num  = parsed.get('month_num')
        budget_gbp = parsed.get('budget_gbp')
        keyword    = parsed.get('keyword', '')
        label      = parsed.get('label', text[:50])

        if not dest_key or dest_key not in DEST_CONFIG:
            send_text(sender,
                "❌ Destinasyon anlaşılamadı.\n\n"
                "Örnek:\n"
                "  *takip et: londra eylül 799*\n"
                "  *takip et: almanya masalı turu ağustos 900*"
            )
            return

        ok, config_id, _ = add_watch_config(
            sender, dest_key, month_num, budget_gbp, keyword, label
        )
        if not ok:
            send_text(sender, "❌ Takip oluşturulamadı.")
            return

        # Özet mesaj
        cfg      = DEST_CONFIG[dest_key]
        month_s  = MONTH_TR_REV.get(month_num, '') if month_num else 'Tüm aylar'
        budget_s = f"£{budget_gbp:.0f}" if budget_gbp else 'Sınırsız'
        kw_s     = f"\n🔤 Keyword: _{keyword}_" if keyword else ''

        send_text(sender,
            f"✅ *Takip #{config_id} Oluşturuldu*\n\n"
            f"{cfg['flag']} Destinasyon: *{cfg['label']}*\n"
            f"📅 Ay filtresi: *{month_s}*\n"
            f"💰 Bütçe: *{budget_s}*{kw_s}\n\n"
            f"🔔 Günde 3 kez kontrol edilecek (08:00, 14:00, 20:00)\n"
            f"📊 %2 ve üzeri fiyat değişiminde bildirim gelecek.\n\n"
            f"_İlk sonuçlar sonraki kontrol döngüsünde toplanacak._"
        )
        return

    # ── TAKİP LİSTESİ ─────────────────────────────────
    if action == 'TAKIPLER':
        from tracker import list_configs, MONTH_TR_REV
        from scraper import DEST_CONFIG

        configs = list_configs(sender)
        if not configs:
            send_text(sender,
                "📋 Aktif takibiniz yok.\n\n"
                "Örnek:\n"
                "  *takip et: londra eylül 799*\n"
                "  *takip et: almanya masalı turu ağustos 900*"
            )
            return

        lines = [f"📋 *Aktif Takipler ({len(configs)})*\n"]
        for c in configs:
            cfg     = DEST_CONFIG.get(c['dest_key'], {})
            flag    = cfg.get('flag','✈️')
            month_s = MONTH_TR_REV.get(c['month_num'],'Tüm aylar') if c['month_num'] else 'Tüm aylar'
            budget_s = f"£{c['budget_gbp']:.0f}" if c['budget_gbp'] else 'Sınırsız'
            kw_s    = f" | _{c['keyword']}_" if c['keyword'] else ''
            last    = c['last_check'][:10] if c['last_check'] else 'Henüz kontrol yok'
            lines.append(
                f"\n*#{c['id']}* {flag} {c['label']}\n"
                f"   📅 {month_s} | 💰 {budget_s}{kw_s}\n"
                f"   📊 {c['tour_count']} tur takipte | Son: {last}"
            )

        lines.append("\n\n_Silmek için: takip sil 1_")
        send_text(sender, '\n'.join(lines))
        return

    # ── TAKİP SİL ─────────────────────────────────────
    if action == 'TAKIP_SIL':
        from tracker import list_configs, remove_config
        import re

        num_m = re.search(r'\b(\d+)\b', text)
        if num_m:
            config_id = int(num_m.group(1))
            ok, msg = remove_config(sender, config_id)
            send_text(sender, msg)
        else:
            configs = list_configs(sender)
            if not configs:
                send_text(sender, "Aktif takip yok.")
            else:
                send_text(sender, "Hangi takibi silmek istiyorsun? Numara gönder.\n_takipler_ yazarak listeyi gör.")
        return

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
