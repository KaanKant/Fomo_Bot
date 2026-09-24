#!/usr/bin/env python3
"""
Fiyat takibi teşhisi
====================
Kayıtlı her sinyal için DexScreener'ın coini bulup bulamadığına bakar; bulamadığı
coinleri GeckoTerminal'e sorar. Amaç: rapordaki -%100'lerin gerçek çöküş mü yoksa
"fiyat bulunamadı" yüzünden oluşan ölçüm hatası mı olduğunu ayırt etmek.

Sonuç: TAKIP-TANI.md (depoya yazılır). Telegram'a hiçbir şey gönderilmez.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import bot

ROOT = Path(__file__).resolve().parent


def gecko_token_price(chain, addr):
    """GeckoTerminal'de token hâlâ var mı, fiyatı kaç?"""
    network = bot.GECKO_NETWORKS.get(chain)
    if not network:
        return None
    d = bot.get_json(f"{bot.GECKO}/networks/{network}/tokens/{addr}",
                     headers={"Accept": "application/json;version=20230302"})
    time.sleep(2.1)
    if not d:
        return None
    a = (d.get("data") or {}).get("attributes") or {}
    return {"price": bot.fnum(a.get("price_usd")),
            "liq": bot.fnum(a.get("total_reserve_in_usd")),
            "mc": bot.fnum(a.get("market_cap_usd")) or bot.fnum(a.get("fdv_usd"))}


def main():
    cfg = bot.load_config()
    state = bot.load_state()
    now = time.time()
    sigs = state.get("signals", [])

    # DexScreener'a toplu sor
    by_chain = {}
    for x in sigs:
        by_chain.setdefault(x["chain"], []).append(x["addr"])
    dex = {}
    for chain, addrs in by_chain.items():
        dex[chain] = bot.fetch_pairs(chain, list(dict.fromkeys(addrs)))

    satirlar, bulunamayan = [], []
    for x in sigs:
        p = dex.get(x["chain"], {}).get(x["addr"])
        dex_price = bot.fnum(p.get("priceUsd")) if p else 0.0
        kaynak = ", ".join(x.get("sources") or ["?"])
        satirlar.append({"x": x, "dex": dex_price, "kaynak": kaynak})
        if dex_price <= 0:
            bulunamayan.append(satirlar[-1])

    # DexScreener'ın bulamadıklarını GeckoTerminal'e sor (limit: ilk 25)
    for s in bulunamayan[:25]:
        g = gecko_token_price(s["x"]["chain"], s["x"]["addr"])
        s["gecko"] = g

    md = ["# Fiyat takibi teşhisi", "",
          f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
          f"Kayıtlı sinyal: {len(sigs)} | DexScreener'da bulunamayan: {len(bulunamayan)}", "",
          "| Coin | Kaynak | Yaş (saat) | Giriş | Zirve (kayıtlı) | DexScreener şimdi | "
          "GeckoTerminal şimdi | Durum |",
          "|---|---|---|---|---|---|---|---|"]

    sayac = {"takip ediliyor": 0, "ölçülemiyor": 0, "gerçekten düşmüş": 0}
    for s in sorted(satirlar, key=lambda s: s["x"]["ts"], reverse=True):
        x, dp = s["x"], s["dex"]
        g = (s.get("gecko") or {})
        gp = g.get("price", 0.0)
        yas = (now - x["ts"]) / 3600
        if dp > 0:
            durum = "takip ediliyor"
        elif gp > 0:
            durum = "ÖLÇÜLEMİYOR (Gecko'da var, Dex'te yok)"
            sayac["ölçülemiyor"] += 1
        else:
            durum = "iki kaynakta da yok"
        if dp > 0:
            sayac["takip ediliyor"] += 1
        md.append(f"| {x.get('symbol', '?')[:16]} | {s['kaynak']} | {yas:.1f} | "
                  f"{x.get('price', 0):.8g} | {bot.fnum(x.get('peak_price')):.8g} | "
                  f"{dp:.8g} | {gp:.8g} | {durum} |")

    md += ["", "## Özet", "",
           f"- DexScreener fiyat veriyor: **{sayac['takip ediliyor']}** sinyal",
           f"- DexScreener vermiyor ama GeckoTerminal veriyor (ölçüm hatası): "
           f"**{sayac['ölçülemiyor']}** sinyal",
           f"- İki kaynakta da yok: **{len(bulunamayan) - sayac['ölçülemiyor']}** sinyal", ""]

    # Kaynağa göre kırılım
    md += ["## Kaynağa göre bulunabilirlik", "",
           "| Kaynak | Sinyal | Dex'te var | Dex'te yok |", "|---|---|---|---|"]
    kk = {}
    for s in satirlar:
        kk.setdefault(s["kaynak"], [0, 0])
        kk[s["kaynak"]][0] += 1
        if s["dex"] > 0:
            kk[s["kaynak"]][1] += 1
    for k, (toplam, var) in sorted(kk.items(), key=lambda kv: -kv[1][0]):
        md.append(f"| {k} | {toplam} | {var} | {toplam - var} |")
    md.append("")

    (ROOT / "TAKIP-TANI.md").write_text("\n".join(md), encoding="utf-8")
    print(f"TAKIP-TANI.md yazildi: {len(sigs)} sinyal, {len(bulunamayan)} bulunamadi")


if __name__ == "__main__":
    main()
