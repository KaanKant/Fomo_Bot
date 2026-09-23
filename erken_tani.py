#!/usr/bin/env python3
"""
Erken giriş teşhisi
===================
Canlı GeckoTerminal havuzlarını çeker, her biri için erken giriş filtrelerinin
verdiği kararı ve ham sayıları bir tabloya yazar. Telegram'a hiçbir şey gönderilmez.

Amaç: eşikleri (buyers15_min, liq_min, mc aralığı...) gerçek sayılara bakarak ayarlamak.
Sonuç: ERKEN-RAPORU.md (depoya yazılır)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import bot

ROOT = Path(__file__).resolve().parent


def main():
    cfg = bot.load_config()
    e = cfg.get("erken") or {}
    pools = []
    for chain in e.get("chains", ["solana"]):
        for page in range(1, int(e.get("new_pool_pages", 8)) + 1):
            pools += bot.gecko_pools(chain, "new_pools", page)
        pools += bot.gecko_pools(chain, "trending_pools")

    uniq = {}
    for p in pools:
        key = f"{p['chain']}:{p['addr']}"
        if key not in uniq or p["liq"] > uniq[key]["liq"]:
            uniq[key] = p
    rows = sorted(uniq.values(), key=lambda p: -p["buyers15"])

    gecenler = []
    md = ["# Erken giriş teşhisi", "",
          f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
          f"İncelenen havuz: {len(rows)}", "",
          "| Coin | Yaş (dk) | MC | Likidite | Lik/MC | 1s hacim | 15dk alıcı | satıcı | 5dk alıcı | Sonuç |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for p in rows[:60]:
        why = bot.early_filter(p, e)
        if not why:
            gecenler.append(p)
        oran = (p["liq"] / p["mc"] * 100) if p["mc"] else 0
        yas = f"{p['age_min']:.0f}" if p["age_min"] is not None else "?"
        md.append(f"| {p['name'][:18]} | {yas} | {bot.money(p['mc'])} | {bot.money(p['liq'])} | "
                  f"%{oran:.0f} | {bot.money(p['vol1'])} | {p['buyers15']} | {p['sellers15']} | "
                  f"{p['buyers5']} | {'**GEÇTİ**' if not why else why} |")

    md += ["", f"## Davranış filtresini geçen: {len(gecenler)}", ""]
    for p in gecenler:
        sec = bot.insider_check(p["addr"])
        if not sec:
            md.append(f"- {p['name']}: güvenlik verisi alınamadı")
            continue
        md.append(f"- **{p['name']}** (`{p['addr']}`) — mint/freeze kapalı: {sec['mint_ok']}, "
                  f"LP kilitli: {sec['lp_locked']}, insider/bundle: %{sec['insider_pct']}, "
                  f"dev: %{sec['creator_pct']}, holder: {sec['holders']}, "
                  f"riskler: {', '.join(sec['danger']) or 'yok'}")

    md += ["", "## Kullanılan eşikler", ""]
    md += [f"- {k}: {v}" for k, v in e.items()]
    md.append("")
    (ROOT / "ERKEN-RAPORU.md").write_text("\n".join(md), encoding="utf-8")
    print(f"ERKEN-RAPORU.md yazıldı: {len(rows)} havuz, {len(gecenler)} geçti")


if __name__ == "__main__":
    main()
