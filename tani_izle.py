#!/usr/bin/env python3
"""
Cüzdan takibi teşhisi
=====================
Takip edilen cüzdanın son işlemlerinde botun TAM OLARAK ne gördüğünü yazar:
kaç işlem geldi, kaçından alım çıkardı, her alım hangi filtreye takıldı.

Sonuç: IZLE-TANI.md
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import bot

ROOT = Path(__file__).resolve().parent


def main():
    cfg = bot.load_config()
    c = cfg.get("cuzdan_takip") or {}
    now = time.time()
    md = ["# Cüzdan takibi teşhisi", "",
          f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC", "",
          f"- HELIUS_API_KEY tanımlı: {bool(os.environ.get('HELIUS_API_KEY', '').strip())}",
          f"- Takip edilen cüzdan sayısı: {len(c.get('cuzdanlar', []))}", ""]

    sol_usd = bot.sol_fiyati()
    md.append(f"- SOL fiyatı: ${sol_usd:,.2f}")

    for w in c.get("cuzdanlar", []):
        adres = w.get("adres", "")
        md += ["", f"## {w.get('ad')} (`{adres}`)", ""]

        ham = bot.get_json(bot.HELIUS_ADDR.format(addr=adres),
                           params={"api-key": os.environ.get("HELIUS_API_KEY", "").strip(),
                                   "limit": 100}, timeout=30)
        md.append(f"- Helius'tan gelen işlem sayısı: **{len(ham or [])}**")
        if ham:
            tipler = {}
            for tx in ham:
                tipler[tx.get("type", "?")] = tipler.get(tx.get("type", "?"), 0) + 1
            md.append(f"- İşlem tipleri: {json.dumps(tipler, ensure_ascii=False)}")
            en_yeni = max((tx.get("timestamp") or 0) for tx in ham)
            en_eski = min((tx.get("timestamp") or 0) for tx in ham)
            md.append(f"- Kapsanan süre: son {(now - en_eski)/60:.0f} dakika "
                      f"(en yeni işlem {(now - en_yeni)/60:.1f} dk önce)")

        alimlar = bot.cuzdan_alimlari(adres, sol_usd)
        md += ["", f"- Çıkarılan ALIM sayısı: **{len(alimlar)}**", "",
               "| Coin (mint) | Kaç dk önce | Alım $ | MC | Karar |", "|---|---|---|---|---|"]

        for a in sorted(alimlar, key=lambda x: -x["ts"])[:25]:
            yas_dk = (now - a["ts"]) / 60
            karar = "GEÇER"
            mc_str = "-"
            if yas_dk > c.get("lookback_hours", 6) * 60:
                karar = f"çok eski ({c.get('lookback_hours')} saat sınırı)"
            elif a["usd"] < c.get("min_usd", 200):
                karar = f"alım küçük (min ${c.get('min_usd')})"
            else:
                pair = bot.fetch_pairs("solana", [a["mint"]]).get(a["mint"])
                if not pair:
                    karar = "DexScreener'da çift yok"
                else:
                    mc = bot.fnum(pair.get("marketCap"))
                    mc_str = bot.money(mc)
                    if mc and mc > c.get("mc_max", 5_000_000):
                        karar = f"MC çok büyük (üst sınır {bot.money(c.get('mc_max'))})"
            md.append(f"| `{a['mint'][:16]}...` | {yas_dk:.0f} | ${a['usd']:,.0f} | {mc_str} | {karar} |")

        gecen = [a for a in alimlar
                 if (now - a["ts"]) / 60 <= c.get("lookback_hours", 6) * 60
                 and a["usd"] >= c.get("min_usd", 200)]
        md += ["", f"- Yaş ve tutar filtresini geçen: **{len(gecen)}**", ""]

    md += ["## Mevcut ayarlar", ""]
    md += [f"- {k}: {v}" for k, v in c.items() if k != "cuzdanlar"]
    md.append("")

    (ROOT / "IZLE-TANI.md").write_text("\n".join(md), encoding="utf-8")
    print("IZLE-TANI.md yazildi")


if __name__ == "__main__":
    main()
