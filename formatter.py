from datetime import datetime

RANK_EMOJIS = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣','7️⃣','8️⃣','9️⃣','🔟',
               '1️⃣1️⃣','1️⃣2️⃣','1️⃣3️⃣','1️⃣4️⃣','1️⃣5️⃣','1️⃣6️⃣','1️⃣7️⃣','1️⃣8️⃣','1️⃣9️⃣','2️⃣0️⃣']

SOURCE_LABELS = {
    'tatilsepeti': '🌐 tatilsepeti.com',
    'jollytur':    '🌐 jollytur.com',
    'etstur':      '🌐 etstur.com',
    'setur':       '🌐 setur.com.tr',
}


def format_tour_card(tour: dict, rank: int, target_gbp: float) -> str:
    diff     = tour['price_gbp'] - target_gbp
    abs_diff = abs(diff)

    if abs_diff < 5:
        diff_icon, diff_str = '🎯', f'±£{abs_diff:.0f}'
    elif diff > 0:
        diff_icon, diff_str = '🔺', f'+£{abs_diff:.0f}'
    else:
        diff_icon, diff_str = '🔻', f'-£{abs_diff:.0f}'

    emoji        = RANK_EMOJIS[rank] if rank < len(RANK_EMOJIS) else f'#{rank+1}'
    source_label = SOURCE_LABELS.get(tour.get('source', ''), '🌐 ?')

    nights_str = f"{tour['nights']} gece" if tour['nights'] else ''
    date_str   = ''
    if tour['start_fmt'] and tour['end_fmt']:
        date_str = f"{tour['start_fmt']} → {tour['end_fmt']}"
    elif tour['start_fmt']:
        date_str = tour['start_fmt']

    desc = tour.get('description', '').strip()
    if desc.lower() in ('londra', '', 'london'):
        desc = ''
    if len(desc) > 100:
        desc = desc[:97] + '...'

    lines = [
        f"{emoji}  <b>£{tour['price_gbp']:.0f}</b>  {diff_icon} {diff_str}  <i>({tour['price_eur']:.0f}€)</i>",
        f"<b>{tour['name']}</b>",
    ]
    if desc:
        lines.append(f"📍 <i>{desc}</i>")
    if date_str:
        line = f"📅 {date_str}"
        if nights_str:
            line += f"  •  🌙 {nights_str}"
        lines.append(line)
    elif nights_str:
        lines.append(f"🌙 {nights_str}")

    lines.append(source_label)
    if tour.get('url'):
        lines.append(f"🔗 <a href='{tour['url']}'>Tura Git →</a>")
    lines.append("")
    return '\n'.join(lines)


def format_results(tours: list[dict], target_gbp: float, rates: dict, dest_key: str = "londra") -> list[str]:
    now     = datetime.now().strftime('%d.%m.%Y %H:%M')
    gbp_try = rates.get('GBP_TRY', 0)
    eur_gbp = rates.get('EUR_GBP', 0)

    # Kaynak dağılımı
    sources = {}
    for t in tours:
        s = t.get('source', '?')
        sources[s] = sources.get(s, 0) + 1
    src_str = '  '.join(
        f"{SOURCE_LABELS.get(s, s).replace('🌐 ','')}: {n}"
        for s, n in sorted(sources.items())
    )

    header = (
        f"🏴󠁧󠁢󠁥󠁮󠁧󠁿 <b>Londra Tur Sonuçları</b>\n"
        f"💰 <b>£{target_gbp:.0f}</b> ve altındaki turlar — <b>{len(tours)} sonuç</b>\n"
        f"💱 1 GBP = {gbp_try:.2f} TRY  |  1€ = £{eur_gbp:.3f}\n"
        f"🕐 {now}  •  {src_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not tours:
        return [header + "❌ Bu fiyatın altında tur bulunamadı."]

    messages: list[str] = []
    current = header

    for i, tour in enumerate(tours):
        card = format_tour_card(tour, i, target_gbp)
        if len(current) + len(card) > 4000:
            messages.append(current.strip())
            current = card
        else:
            current += card

    if current.strip():
        messages.append(current.strip())

    # Son mesaja özet ekle
    if messages:
        messages[-1] += f"\n\n<i>Toplam {len(tours)} tur listelendi.</i>"

    return messages
