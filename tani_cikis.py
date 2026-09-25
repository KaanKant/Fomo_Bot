#!/usr/bin/env python3
"""
Çıkış kuralı backtest'i
=======================
Kayıtların fiyat geçmişi üzerinde "kâr al / zarar kes / süre limiti" kombinasyonlarını
dener ve hangisinin toplam getiriyi en yükseğe çıkardığını ölçer.

Neden: sinyallerin medyan zirvesi artıda ama tutunca hepsi eriyor. Yani kazancı
belirleyen şey giriş değil çıkış. Bu betik "hangi çıkış kuralı" sorusunu veriyle yanıtlar.

Varsayımlar (dürüstlük için açıkça yazılıyor):
- Kâr al: limit emir kabul edilir, tam hedef fiyattan dolar.
- Zarar kes: piyasa emri kabul edilir, o anki ÖLÇÜLEN fiyattan dolar (kötümser).
- Fiyat ölçümleri ~10 dakikada bir. İki ölçüm arasındaki ani sıçramalar görünmez,
  yani kâr al sonuçları GERÇEKTEN OLABİLECEĞİNDEN DÜŞÜK çıkar.
- Ücret ve kayma dahil değil. Gerçek sonuç bunlardan dolayı daha kötü olur.

Sonuç: CIKIS-RAPORU.md (depoya yazılır).
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path

import bot

ROOT = Path(__file__).resolve().parent

KAR_AL = [20, 30, 50, 75, 100, 150, 200]        # %
ZARAR_KES = [None, -30, -50, -70]               # %
SURE = [30, 60, 120, 240, 720, 1440]            # dakika
UCRET = 2.0                                      # her işlem için toplam % maliyet varsayımı


def kayitlar(state):
    """Fiyat geçmişi yeterli olan kayıtlar (gölge + bildirilen sinyaller)."""
    out = []
    for g in state.get("golge", []):
        if len(g.get("hist") or []) >= 3 and bot.fnum(g.get("price")) > 0:
            out.append(("gölge", g))
    for s in state.get("signals", []):
        if len(s.get("hist") or []) >= 3 and bot.fnum(s.get("price")) > 0:
            out.append(("sinyal", s))
    return out


def simule(kayit, kar_al, zarar_kes, sure):
    """Tek kayıt için kuralı uygular, yüzde getiriyi döndürür."""
    giris = bot.fnum(kayit.get("price"))
    hist = kayit.get("hist") or []
    # Yüzde yerine fiyat seviyesiyle karşılaştır: kayan nokta yüzünden hedefe tam
    # denk gelen fiyat (%19.999999 gibi) kaçmasın.
    hedef = giris * (1 + kar_al / 100) * (1 - 1e-9)
    kes = giris * (1 + zarar_kes / 100) * (1 + 1e-9) if zarar_kes is not None else None
    for dk, fiyat in hist:
        if dk == 0:
            continue
        degisim = (fiyat / giris - 1) * 100
        if fiyat >= hedef:
            return kar_al - UCRET              # limit emir hedeften dolar
        if kes is not None and fiyat <= kes:
            return degisim - UCRET             # piyasa emri: ölçülen fiyattan
        if dk >= sure:
            return degisim - UCRET             # süre doldu, çık
    # Süre dolmadan geçmiş bitti: son bilinen fiyat
    son = hist[-1][1]
    return (son / giris - 1) * 100 - UCRET


def dene(kayit_listesi, kar_al, zarar_kes, sure):
    getiriler = [simule(k, kar_al, zarar_kes, sure) for _, k in kayit_listesi]
    kazanan = sum(1 for g in getiriler if g > 0)
    return {
        "kar_al": kar_al, "zarar_kes": zarar_kes, "sure": sure,
        "ortalama": statistics.mean(getiriler),
        "medyan": statistics.median(getiriler),
        "kazanan": kazanan,
        "kazanma_orani": kazanan * 100 // len(getiriler),
        "toplam": sum(getiriler),
    }


def main():
    state = bot.load_state()
    kl = kayitlar(state)
    now = datetime.now(timezone.utc)

    md = ["# Çıkış kuralı backtest'i", "",
          f"Tarih: {now.strftime('%Y-%m-%d %H:%M')} UTC",
          f"Test edilen kayıt: **{len(kl)}** "
          f"(gölge {sum(1 for t, _ in kl if t == 'gölge')}, "
          f"bildirilen sinyal {sum(1 for t, _ in kl if t == 'sinyal')})", ""]

    if len(kl) < 20:
        md += ["Anlamlı sonuç için en az 20 kayıt gerekiyor. Bot çalıştıkça artacak.", ""]
        (ROOT / "CIKIS-RAPORU.md").write_text("\n".join(md), encoding="utf-8")
        print(f"Yetersiz kayit: {len(kl)}")
        return

    # Karşılaştırma tabanları
    tut = []
    zirvede_sat = []
    for _, k in kl:
        giris = bot.fnum(k.get("price"))
        son = bot.fnum(k.get("last_price"))
        zirve = bot.fnum(k.get("peak_price"))
        tut.append(((son / giris - 1) * 100 if son else -100.0) - UCRET)
        zirvede_sat.append(((zirve / giris - 1) * 100 if zirve else -100.0) - UCRET)

    md += ["## Karşılaştırma tabanı", "",
           "| Strateji | Ortalama getiri | Medyan | Kazanan |", "|---|---|---|---|",
           f"| Hiç satma (tut) | {statistics.mean(tut):+.1f}% | {statistics.median(tut):+.1f}% | "
           f"{sum(1 for g in tut if g > 0)}/{len(tut)} |",
           f"| Tam zirvede sat (imkânsız) | {statistics.mean(zirvede_sat):+.1f}% | "
           f"{statistics.median(zirvede_sat):+.1f}% | "
           f"{sum(1 for g in zirvede_sat if g > 0)}/{len(zirvede_sat)} |", "",
           "*Gerçekçi her kural bu ikisinin arasında kalır.*", ""]

    sonuclar = []
    for ka in KAR_AL:
        for zk in ZARAR_KES:
            for s in SURE:
                sonuclar.append(dene(kl, ka, zk, s))
    sonuclar.sort(key=lambda r: -r["ortalama"])

    md += ["## En iyi 15 kural", "",
           "| Kâr al | Zarar kes | Süre limiti | Ortalama getiri | Medyan | Kazanma oranı |",
           "|---|---|---|---|---|---|"]
    for r in sonuclar[:15]:
        md.append(f"| +%{r['kar_al']} | {('%' + str(r['zarar_kes'])) if r['zarar_kes'] else 'yok'} | "
                  f"{r['sure']} dk | **{r['ortalama']:+.1f}%** | {r['medyan']:+.1f}% | "
                  f"%{r['kazanma_orani']} ({r['kazanan']}/{len(kl)}) |")

    md += ["", "## En kötü 5 kural", "",
           "| Kâr al | Zarar kes | Süre limiti | Ortalama getiri |", "|---|---|---|---|"]
    for r in sonuclar[-5:]:
        md.append(f"| +%{r['kar_al']} | {('%' + str(r['zarar_kes'])) if r['zarar_kes'] else 'yok'} | "
                  f"{r['sure']} dk | {r['ortalama']:+.1f}% |")

    # Tek tek etkiler: sadece kâr al hedefi değişse ne olur?
    md += ["", "## Sadece kâr al hedefinin etkisi", "",
           "*(zarar kes yok, süre limiti 24 saat)*", "",
           "| Kâr al | Ortalama getiri | Kazanma oranı |", "|---|---|---|"]
    for ka in KAR_AL:
        r = dene(kl, ka, None, 1440)
        md.append(f"| +%{ka} | {r['ortalama']:+.1f}% | %{r['kazanma_orani']} |")

    md += ["", "## Sadece süre limitinin etkisi", "",
           "*(kâr al +%50, zarar kes yok)*", "",
           "| Süre | Ortalama getiri | Kazanma oranı |", "|---|---|---|"]
    for s in SURE:
        r = dene(kl, 50, None, s)
        md.append(f"| {s} dk | {r['ortalama']:+.1f}% | %{r['kazanma_orani']} |")

    en = sonuclar[0]
    md += ["", "## Sonuç", "",
           f"En iyi kural: **+%{en['kar_al']} kâr al**, "
           f"**{('zarar kes %' + str(en['zarar_kes'])) if en['zarar_kes'] else 'zarar kes yok'}**, "
           f"**{en['sure']} dakika süre limiti** → ortalama {en['ortalama']:+.1f}% "
           f"(kazanma oranı %{en['kazanma_orani']})", "",
           f"Karşılaştırma: hiç satmasan ortalama {statistics.mean(tut):+.1f}%.", "",
           "**Uyarılar:** ücret/kayma için işlem başına %" f"{UCRET:.0f} düşüldü, gerçekte daha "
           "yüksek olabilir. Fiyatlar 10 dakikada bir ölçüldüğü için ani sıçramalar "
           "görünmüyor. Geçmişte iyi çalışan kural gelecekte çalışmayabilir.", ""]

    (ROOT / "CIKIS-RAPORU.md").write_text("\n".join(md), encoding="utf-8")
    print(f"CIKIS-RAPORU.md yazildi ({len(kl)} kayit, en iyi ortalama {en['ortalama']:+.1f}%)")


if __name__ == "__main__":
    main()
