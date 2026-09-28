#!/usr/bin/env python3
"""
Deployer geçmişi teşhisi
========================
RugCheck cevabındaki `creatorTokens` alanının YAPISINI raporlar: tipi, kaç
kayıt geldiği, hangi alanların bulunduğu ve sayısal alanların dağılımı.

Adres ve token adı YAZMAZ - depo herkese açık, ayrıca burada bize lazım olan
şey içerik değil şekil. Amacı tek: "kurucunun eski tokenları" filtresini
tahminle değil, gerçek alan adlarıyla yazabilmek.

Sonuç: DEPLOYER-TANI.md
"""
from __future__ import annotations

import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import bot

ROOT = Path(__file__).resolve().parent
ORNEK = 15          # kaç coinin raporuna bakılsın


def tip_adi(x):
    if x is None:
        return "null"
    if isinstance(x, bool):
        return "bool"
    if isinstance(x, (int, float)):
        return "sayı"
    if isinstance(x, str):
        return "metin"
    if isinstance(x, list):
        return f"liste[{len(x)}]"
    if isinstance(x, dict):
        return "sözlük"
    return type(x).__name__


def main():
    cfg = bot.load_config()
    e = cfg.get("erken") or {}

    # Adayları normal akıştan al: yeni havuzlar + trend
    pools = []
    for page in range(1, 4):
        pools += bot.gecko_pools("solana", "new_pools", page)
    pools += bot.gecko_pools("solana", "trending_pools")
    uniq = {}
    for p in pools:
        if p["addr"] not in uniq or p["liq"] > uniq[p["addr"]]["liq"]:
            uniq[p["addr"]] = p
    # Yaşı bizim ilgi alanımıza yakın olanları öne al
    adaylar = sorted(uniq.values(), key=lambda p: -(p.get("vol1") or 0))[:ORNEK]

    md = ["# Deployer geçmişi teşhisi", "",
          f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
          f"İncelenen coin: {len(adaylar)}", "",
          "> Bu rapor bilerek adres ve token adı yazmaz; sadece alanın yapısını "
          "gösterir. Amaç `creatorTokens` filtresini doğru alan adlarıyla yazmak.", ""]

    tipler, uzunluklar, alan_sayaci, alan_tipleri = {}, [], {}, {}
    sayisal = {}
    yok = 0

    for p in adaylar:
        rep = bot.get_json(bot.RUGCHECK.format(mint=p["addr"]))
        time.sleep(0.6)
        if not rep:
            yok += 1
            continue
        ct = rep.get("creatorTokens")
        t = tip_adi(ct) if not isinstance(ct, list) else "liste"
        tipler[t] = tipler.get(t, 0) + 1
        if isinstance(ct, list):
            uzunluklar.append(len(ct))
            for kayit in ct:
                if isinstance(kayit, dict):
                    for k, v in kayit.items():
                        alan_sayaci[k] = alan_sayaci.get(k, 0) + 1
                        alan_tipleri.setdefault(k, set()).add(tip_adi(v))
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            sayisal.setdefault(k, []).append(float(v))
                else:
                    alan_sayaci["<düz değer>"] = alan_sayaci.get("<düz değer>", 0) + 1
                    alan_tipleri.setdefault("<düz değer>", set()).add(tip_adi(kayit))

    md += ["## Alanın tipi", "", "| Tip | Kaç coinde |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in sorted(tipler.items(), key=lambda x: -x[1])]
    md += [f"| (rapor alınamadı) | {yok} |", ""]

    if uzunluklar:
        md += ["## Kurucunun kaç eski tokenı geliyor", "",
               f"- Kayıt sayısı: {len(uzunluklar)} coin",
               f"- En az: {min(uzunluklar)} | Medyan: {statistics.median(uzunluklar):.0f} "
               f"| En çok: {max(uzunluklar)}",
               f"- Boş gelen (0 token): {sum(1 for x in uzunluklar if x == 0)}", ""]

    if alan_sayaci:
        md += ["## Her kaydın içindeki alanlar", "",
               "| Alan | Kaç kez | Tip(ler) |", "|---|---|---|"]
        for k, v in sorted(alan_sayaci.items(), key=lambda x: -x[1]):
            md.append(f"| `{k}` | {v} | {', '.join(sorted(alan_tipleri.get(k, [])))} |")
        md.append("")

    if sayisal:
        md += ["## Sayısal alanların dağılımı", "",
               "| Alan | Adet | En düşük | Medyan | En yüksek |", "|---|---|---|---|---|"]
        for k, vals in sorted(sayisal.items()):
            md.append(f"| `{k}` | {len(vals)} | {min(vals):,.2f} | "
                      f"{statistics.median(vals):,.2f} | {max(vals):,.2f} |")
        md.append("")

    md += ["## Sonraki adım", "",
           "Alan adları netleştiyse `bot.py` içindeki `insider_check` bu alanı okuyup "
           "iki sayı üretecek: kurucunun kaç eski tokenı var ve kaçı ölmüş. Bu iki sayı "
           "önce sadece gölge kaydına yazılacak, hiçbir adayı elemeyecek.", ""]

    (ROOT / "DEPLOYER-TANI.md").write_text("\n".join(md), encoding="utf-8")
    print(f"DEPLOYER-TANI.md yazıldı: {len(adaylar)} coin, {yok} rapor alınamadı")


if __name__ == "__main__":
    main()
