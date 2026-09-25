#!/usr/bin/env python3
"""
Cüzdan bulucu
=============
Bir trader'ın FOMO'da görünen pozisyonlarından yola çıkıp zincir üstündeki cüzdan
adresini bulur: iki (veya daha fazla) coinin sahip listesini çeker ve kesiştirir.
Aynı anda hem X coininden hem Y coininden tutan cüzdan sayısı genelde tektir.

Tamamen herkese açık zincir verisi kullanılır (Helius). FOMO'nun API'sine dokunulmaz.

Kullanım: MINTLER ortam değişkenine "isim:mint:beklenen_miktar" listesi verilir.
Sonuç: CUZDAN-BUL.md
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

KEY = os.environ.get("HELIUS_API_KEY", "").strip()
RPC = f"https://mainnet.helius-rpc.com/?api-key={KEY}"
ROOT = Path(__file__).resolve().parent
session = requests.Session()

# "isim:mint:beklenen" (beklenen = FOMO'da görünen token adedi, yaklaşık)
VARSAYILAN = "FEELSGOOD:HgcxVs6kJhPAaGqnPNGaa7zYgNT49hJrLufiqcNMuYZT:5100000"


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def sahipler(mint, max_sayfa=25):
    """Mint'in tüm token hesaplarını çeker: {sahip: miktar}"""
    out, sayfa = {}, 1
    while sayfa <= max_sayfa:
        try:
            r = session.post(RPC, json={
                "jsonrpc": "2.0", "id": 1, "method": "getTokenAccounts",
                "params": {"mint": mint, "page": sayfa, "limit": 1000,
                           "options": {"showZeroBalance": False}}}, timeout=40)
            if r.status_code == 429:
                time.sleep(2)
                continue
            r.raise_for_status()
            hesaplar = ((r.json() or {}).get("result") or {}).get("token_accounts") or []
        except (requests.RequestException, ValueError) as e:
            log("  hata:", e)
            break
        if not hesaplar:
            break
        for h in hesaplar:
            sahip = h.get("owner")
            if sahip:
                out[sahip] = out.get(sahip, 0) + int(h.get("amount") or 0)
        log(f"  sayfa {sayfa}: {len(hesaplar)} hesap (toplam {len(out)} sahip)")
        if len(hesaplar) < 1000:
            break
        sayfa += 1
        time.sleep(0.25)
    return out


def ondalik(mint):
    """Token'ın ondalık basamak sayısı."""
    try:
        r = session.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "getAsset",
                                    "params": {"id": mint}}, timeout=30)
        d = (r.json() or {}).get("result") or {}
        return int(((d.get("token_info") or {}).get("decimals")) or 6)
    except (requests.RequestException, ValueError, TypeError):
        return 6


def main():
    if not KEY:
        log("HATA: HELIUS_API_KEY yok")
        raise SystemExit(1)

    girdi = os.environ.get("MINTLER", VARSAYILAN).strip()
    hedefler = []
    for parca in girdi.split(","):
        p = parca.strip().split(":")
        if len(p) >= 2:
            hedefler.append({"isim": p[0], "mint": p[1],
                             "beklenen": float(p[2]) if len(p) > 2 and p[2] else None})

    md = ["# Cüzdan bulucu", "",
          f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC", "",
          "Yöntem: her coinin zincir üstü sahip listesi çekilir, sonra kesiştirilir.", "",
          "| Coin | Mint | Sahip sayısı |", "|---|---|---|"]

    tablolar = []
    for h in hedefler:
        log(f"{h['isim']} sahipleri çekiliyor...")
        s = sahipler(h["mint"])
        h["ondalik"] = ondalik(h["mint"])
        tablolar.append(s)
        md.append(f"| {h['isim']} | `{h['mint']}` | {len(s)} |")
        log(f"{h['isim']}: {len(s)} sahip, {h['ondalik']} ondalık")

    if not tablolar:
        md.append("\nHiç mint verilmedi.")
        (ROOT / "CUZDAN-BUL.md").write_text("\n".join(md), encoding="utf-8")
        return

    ortak = set(tablolar[0])
    for s in tablolar[1:]:
        ortak &= set(s)
    md += ["", f"## Hepsinde birden görünen cüzdan: **{len(ortak)}**", ""]

    # Beklenen miktarlara uyanları öne al
    satirlar = []
    for c in ortak:
        row = {"cuzdan": c, "uyum": 0, "miktarlar": []}
        for h, s in zip(hedefler, tablolar):
            adet = s.get(c, 0) / (10 ** h["ondalik"])
            row["miktarlar"].append((h["isim"], adet, h["beklenen"]))
            if h["beklenen"] and abs(adet - h["beklenen"]) <= h["beklenen"] * 0.08:
                row["uyum"] += 1
        satirlar.append(row)
    satirlar.sort(key=lambda r: (-r["uyum"], -sum(m[1] for m in r["miktarlar"])))

    basliklar = " | ".join(h["isim"] for h in hedefler)
    md += [f"| Cüzdan | {basliklar} | Beklenene uyan |",
           "|---" * (len(hedefler) + 2) + "|"]
    for r in satirlar[:30]:
        mik = " | ".join(f"{a:,.0f}" for _, a, _ in r["miktarlar"])
        md.append(f"| `{r['cuzdan']}` | {mik} | {r['uyum']}/{len(hedefler)} |")

    md += ["", "## Beklenen miktarlar (FOMO'da görünen)", ""]
    for h in hedefler:
        md.append(f"- {h['isim']}: {h['beklenen']:,.0f}" if h["beklenen"]
                  else f"- {h['isim']}: (belirtilmedi)")

    tam = [r for r in satirlar if r["uyum"] == len(hedefler)]
    md += ["", "## Sonuç", ""]
    if len(tam) == 1:
        md.append(f"Tek eşleşme: **`{tam[0]['cuzdan']}`** — bu cüzdan yüksek ihtimalle aradığımız kişi.")
    elif tam:
        md.append(f"{len(tam)} cüzdan tüm miktarlara uyuyor; ayırt etmek için bir coin daha ekle.")
    else:
        md.append("Hiçbir cüzdan beklenen miktarların hepsine uymadı. "
                  "Miktarlar değişmiş olabilir (yeni alım/satım) ya da FOMO pozisyonu "
                  "birden fazla cüzdana dağıtıyor olabilir.")
    md.append("")

    (ROOT / "CUZDAN-BUL.md").write_text("\n".join(md), encoding="utf-8")
    log(f"CUZDAN-BUL.md yazildi: {len(ortak)} ortak cuzdan, {len(tam)} tam uyum")


if __name__ == "__main__":
    main()
