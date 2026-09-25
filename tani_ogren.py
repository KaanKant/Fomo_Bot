#!/usr/bin/env python3
"""
Öğrenme raporu
==============
Gölge kayıtlarını okur ve her ölçüm için sorar: "bu değer yüksekken coin daha çok
mu yükseliyor?" Böylece eşikleri tahminle değil veriyle ayarlayabiliriz.

Sonuç: OGRENME-RAPORU.md (depoya yazılır). Telegram'a hiçbir şey gönderilmez.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path

import bot

ROOT = Path(__file__).resolve().parent

# (ölçüm anahtarı, başlık, eşikler) - eşikler kayıtları gruplara böler
OLCUMLER = [
    ("al15", "15 dk'da farklı alıcı", [200, 400, 700]),
    ("oran", "Alıcı / satıcı oranı", [2, 4, 8]),
    ("likmc", "Likidite / MC", [0.1, 0.2, 0.4]),
    ("mc", "Market cap ($)", [50_000, 100_000, 300_000]),
    ("yas", "Yaş (dakika)", [3, 5, 10]),
    ("vol1", "1 saatlik hacim ($)", [25_000, 75_000, 150_000]),
    ("holder", "Holder sayısı", [300, 800, 1500]),
    ("insider", "Insider/bundle payı (%)", [0.5, 2, 5]),
    ("dev", "Dev cüzdanı (%)", [0.1, 1, 2]),
]

BASARI = 30      # "tuttu" sayılmak için zirvede gereken yüzde


def yuzde(g):
    """Girişten sonra görülen en yüksek yükseliş (%)"""
    giris = bot.fnum(g.get("price"))
    zirve = bot.fnum(g.get("peak_price"))
    return (zirve / giris - 1) * 100 if giris and zirve else -100.0


def simdi(g):
    giris = bot.fnum(g.get("price"))
    son = bot.fnum(g.get("last_price"))
    return (son / giris - 1) * 100 if giris and son else -100.0


def ozet(kayitlar):
    if not kayitlar:
        return None
    z = [yuzde(g) for g in kayitlar]
    s = [simdi(g) for g in kayitlar]
    tuttu = sum(1 for x in z if x >= BASARI)
    return (f"{len(kayitlar)} | medyan zirve {statistics.median(z):+.0f}% | "
            f"medyan şimdi {statistics.median(s):+.0f}% | "
            f"+%{BASARI} gören: {tuttu} ({tuttu*100//len(kayitlar)}%)")


def grupla(kayitlar, anahtar, esikler):
    """Kayıtları eşiklere göre gruplara böler."""
    gruplar = {}
    etiketler = ([f"< {esikler[0]:g}"] +
                 [f"{esikler[i]:g} - {esikler[i+1]:g}" for i in range(len(esikler) - 1)] +
                 [f"{esikler[-1]:g} +"])
    for g in kayitlar:
        v = (g.get("o") or {}).get(anahtar)
        if v is None:
            continue
        i = sum(1 for e in esikler if bot.fnum(v) >= e)
        gruplar.setdefault(etiketler[i], []).append(g)
    return etiketler, gruplar


def main():
    state = bot.load_state()
    golge = state.get("golge", [])
    now = datetime.now(timezone.utc)

    md = ["# Öğrenme raporu", "",
          f"Tarih: {now.strftime('%Y-%m-%d %H:%M')} UTC",
          f"Kayıt sayısı: **{len(golge)}**", ""]

    if len(golge) < 10:
        md += ["Anlamlı bir sonuç için en az 10-20 kayıt gerekiyor. "
               "Bot çalışmaya devam ettikçe bu sayı artacak.", ""]
        (ROOT / "OGRENME-RAPORU.md").write_text("\n".join(md), encoding="utf-8")
        print(f"Yetersiz kayit: {len(golge)}")
        return

    md += ["## Genel", "", f"Tümü: {ozet(golge)}", "",
           f"*(\"+%{BASARI} gören\" = girişten sonra bir ara en az %{BASARI} yükselen kayıt sayısı)*",
           "", "## Ölçüm ölçüm kırılım", "",
           "Her ölçüm için: değer arttıkça sonuç iyileşiyor mu?", ""]

    for anahtar, baslik, esikler in OLCUMLER:
        etiketler, gruplar = grupla(golge, anahtar, esikler)
        if len(gruplar) < 2:
            continue
        md += [f"### {baslik}", "",
               "| Aralık | Kayıt | Medyan zirve | Medyan şimdi | +%{} gören |".format(BASARI),
               "|---|---|---|---|---|"]
        for e in etiketler:
            k = gruplar.get(e)
            if not k:
                continue
            z = [yuzde(g) for g in k]
            s = [simdi(g) for g in k]
            t = sum(1 for x in z if x >= BASARI)
            md.append(f"| {e} | {len(k)} | {statistics.median(z):+.0f}% | "
                      f"{statistics.median(s):+.0f}% | {t} ({t*100//len(k)}%) |")
        md.append("")

    # Kaynağa göre kırılım: erken giriş mi, cüzdan takibi mi daha iyi?
    kaynaklar = {}
    for g in golge:
        kaynaklar.setdefault(g.get("kaynak", "erken"), []).append(g)
    if len(kaynaklar) > 1:
        md += ["### Kaynağa göre", "",
               "| Kaynak | Kayıt | Medyan zirve | Medyan şimdi | +%{} gören |".format(BASARI),
               "|---|---|---|---|---|"]
        for k, kl in sorted(kaynaklar.items(), key=lambda kv: -len(kv[1])):
            z = [yuzde(g) for g in kl]
            sm = [simdi(g) for g in kl]
            t = sum(1 for x in z if x >= BASARI)
            md.append(f"| {k} | {len(kl)} | {statistics.median(z):+.0f}% | "
                      f"{statistics.median(sm):+.0f}% | {t} ({t*100//len(kl)}%) |")
        md.append("")

    # launchpad / DEX kırılımı
    md += ["### Havuz tipi", "", "| Tip | Kayıt | Medyan zirve | +%{} gören |".format(BASARI),
           "|---|---|---|---|"]
    for etiket, sec in (("launchpad (bonding curve)", True), ("normal DEX", False)):
        k = [g for g in golge if bool((g.get("o") or {}).get("launchpad")) is sec]
        if not k:
            continue
        z = [yuzde(g) for g in k]
        t = sum(1 for x in z if x >= BASARI)
        md.append(f"| {etiket} | {len(k)} | {statistics.median(z):+.0f}% | {t} ({t*100//len(k)}%) |")
    md.append("")

    # En iyi kayıtlar: ortak yönleri var mı?
    sirali = sorted(golge, key=yuzde, reverse=True)
    md += ["## En çok yükselen 10 kayıt", "",
           "| Coin | Zirve | Şimdi | Alıcı15 | Oran | Lik/MC | MC | Yaş | Holder | DEX |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for g in sirali[:10]:
        o = g.get("o") or {}
        md.append(f"| {g.get('symbol','?')[:14]} | {yuzde(g):+.0f}% | {simdi(g):+.0f}% | "
                  f"{o.get('al15','?')} | {o.get('oran','?')} | {o.get('likmc','?')} | "
                  f"{bot.money(o.get('mc',0))} | {o.get('yas','?')} | {o.get('holder','?')} | "
                  f"{o.get('dex','?')} |")

    md += ["", "## En çok düşen 5 kayıt", "",
           "| Coin | Zirve | Şimdi | Alıcı15 | Oran | Lik/MC | MC | Yaş | Holder | DEX |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for g in sirali[-5:]:
        o = g.get("o") or {}
        md.append(f"| {g.get('symbol','?')[:14]} | {yuzde(g):+.0f}% | {simdi(g):+.0f}% | "
                  f"{o.get('al15','?')} | {o.get('oran','?')} | {o.get('likmc','?')} | "
                  f"{bot.money(o.get('mc',0))} | {o.get('yas','?')} | {o.get('holder','?')} | "
                  f"{o.get('dex','?')} |")

    # Zirveye ne kadar sürede ulaşılıyor? (çıkış planı için)
    sureler = []
    for g in golge:
        h = g.get("hist") or []
        if len(h) < 2:
            continue
        en = max(h, key=lambda p: p[1])
        if en[1] > bot.fnum(g.get("price")):
            sureler.append(en[0])
    md += ["", "## Zirveye ulaşma süresi", ""]
    if sureler:
        md += [f"- Ölçülebilen kayıt: {len(sureler)}",
               f"- Medyan süre: **{statistics.median(sureler):.0f} dakika**",
               f"- Kayıtların %75'i ilk {sorted(sureler)[int(len(sureler)*0.75)]:.0f} dakikada zirve yapmış",
               "", "*Bu süre, bir çıkış kuralı belirlemek için en önemli sayı.*"]
    else:
        md += ["- Henüz girişin üstüne çıkan kayıt yok."]
    md.append("")

    (ROOT / "OGRENME-RAPORU.md").write_text("\n".join(md), encoding="utf-8")
    print(f"OGRENME-RAPORU.md yazildi ({len(golge)} kayit)")


if __name__ == "__main__":
    main()
