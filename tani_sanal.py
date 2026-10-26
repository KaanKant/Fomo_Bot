#!/usr/bin/env python3
"""
Sanal işlem teşhisi
===================
Sanal işlem kayıtlarını, coinin giriş anındaki ölçümleriyle (gölge kaydı ya da
sinyal kaydı) birleştirip depoya yazar:
  SANAL-ISLEMLER.json : her işlem + ölçümleri + fiyat geçmişi (ayrıntılı analiz için)
  SANAL-RAPORU.md     : kısa özet (kaynak, kapanış sebebi, maliyet payı)
Telegram'a hiçbir şey gönderilmez.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import bot

ROOT = Path(__file__).resolve().parent


def f(x):
    return bot.fnum(x)


def main():
    state = bot.load_state()
    p = state.get("paper") or {}
    islemler = list(p.get("kapali", [])) + [dict(x, acik=True) for x in p.get("acik", [])]
    golge = {g["key"]: g for g in state.get("golge", [])}
    sinyal = {s["key"]: s for s in state.get("signals", [])}

    for x in islemler:
        g = golge.get(x["key"])
        s = sinyal.get(x["key"])
        x["olcum"] = (g or {}).get("o") or {}
        x["puan"] = (s or {}).get("score")
        x["hist"] = ((g or s or {}).get("hist") or [])
        x["hist_ts"] = (g or s or {}).get("ts")
        if not x.get("acik") and x.get("kapanis_fiyat") and x.get("fiyat"):
            # Sadece fiyattan gelen getiri; net ile farkı = ücret + kayma
            x["fiyat_pct"] = round((f(x["kapanis_fiyat"]) / f(x["fiyat"]) - 1) * 100, 1)

    (ROOT / "SANAL-ISLEMLER.json").write_text(
        json.dumps({"tarih": datetime.now(timezone.utc).isoformat(),
                    "bakiye": p.get("bakiye"), "baslangic": p.get("baslangic"),
                    "atlanan": p.get("atlanan"), "islemler": islemler},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    kapali = [x for x in islemler if not x.get("acik")]
    L = ["# Sanal işlem teşhisi", "",
         f"Tarih: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
         f"Bakiye: ${f(p.get('bakiye')):.2f} (başlangıç ${f(p.get('baslangic')):.0f}) | "
         f"kapanan {len(kapali)} | açık {len(islemler) - len(kapali)}", ""]

    def grup(baslik, anahtar):
        g = {}
        for x in kapali:
            g.setdefault(anahtar(x), []).append(x)
        L.extend([f"## {baslik}", "", "| Grup | İşlem | Net $ | Kazanan | Medyan net | Medyan zirve |",
                  "|---|---|---|---|---|---|"])
        for k, rr in sorted(g.items(), key=lambda kv: sum(r["net"] for r in kv[1])):
            L.append(f"| {k} | {len(rr)} | {sum(r['net'] for r in rr):+.2f} | "
                     f"{sum(1 for r in rr if r['net'] > 0)} | "
                     f"{statistics.median(r['net_pct'] for r in rr):+.0f}% | "
                     f"{statistics.median(r.get('zirve_pct', 0) for r in rr):+.0f}% |")
        L.append("")

    if kapali:
        grup("Kaynağa göre", lambda x: x["kaynak"])
        grup("Kapanış sebebine göre", lambda x: x["sebep"])
        maliyet = [x["net_pct"] - x["fiyat_pct"] for x in kapali if "fiyat_pct" in x]
        if maliyet:
            L.append(f"Ücret + kaymanın işlem başına medyan maliyeti: {statistics.median(maliyet):.1f} puan")
    (ROOT / "SANAL-RAPORU.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
