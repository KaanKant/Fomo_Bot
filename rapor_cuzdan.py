#!/usr/bin/env python3
"""
Cüzdan raporu
=============
Takip edilen her cüzdan için AYRI bir rapor dosyası üretir: zincirden alım/satım
akışını çeker, coin bazında ne kadar alınıp ne kadar satıldığını ve elde ne
kaldığını hesaplar.

Tamamen herkese açık zincir verisi (Helius + DexScreener).
Sonuç: CUZDAN-<ad>.md dosyaları.
"""
from __future__ import annotations

import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import bot

ROOT = Path(__file__).resolve().parent
RPC = "https://mainnet.helius-rpc.com/?api-key={key}"
SAYFA = 5          # kaç sayfa işlem geçmişi (sayfa başına 100)


def islemler(adres, key, sayfa=SAYFA):
    """Cüzdanın işlem geçmişi, sayfalama ile."""
    out, before = [], None
    for _ in range(sayfa):
        params = {"api-key": key, "limit": 100}
        if before:
            params["before"] = before
        d = bot.get_json(bot.HELIUS_ADDR.format(addr=adres), params=params, timeout=30)
        if not d:
            break
        out.extend(d)
        before = d[-1].get("signature")
        if len(d) < 100:
            break
        time.sleep(0.25)
    return out


def bakiyeler(adres, key):
    """Cüzdanın şu anki token bakiyeleri: {mint: adet}"""
    try:
        r = bot.session.post(RPC.format(key=key), json={
            "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
            "params": [adres, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                       {"encoding": "jsonParsed"}]}, timeout=30)
        hesaplar = ((r.json() or {}).get("result") or {}).get("value") or []
    except Exception:
        return {}
    out = {}
    for h in hesaplar:
        try:
            info = h["account"]["data"]["parsed"]["info"]
            adet = bot.fnum(info["tokenAmount"]["uiAmount"])
            if adet > 0:
                out[info["mint"]] = out.get(info["mint"], 0.0) + adet
        except (KeyError, TypeError):
            continue
    return out


def akis(txs, adres, sol_usd):
    """Coin bazında alım/satım dolar akışı."""
    per = {}
    for tx in txs:
        ts = tx.get("timestamp") or 0
        girdi, cikti, quote_out, quote_in = {}, {}, 0.0, 0.0
        for t in tx.get("tokenTransfers") or []:
            mint = (t.get("mint") or "")
            amt = bot.fnum(t.get("tokenAmount"))
            if not mint:
                continue
            carpan = sol_usd if mint.lower() == bot.WSOL.lower() else 1.0
            if mint.lower() in bot.QUOTE_TOKENS:
                if t.get("fromUserAccount") == adres:
                    quote_out += amt * carpan
                if t.get("toUserAccount") == adres:
                    quote_in += amt * carpan
            else:
                if t.get("toUserAccount") == adres:
                    girdi[mint] = girdi.get(mint, 0.0) + amt
                if t.get("fromUserAccount") == adres:
                    cikti[mint] = cikti.get(mint, 0.0) + amt
        for n in tx.get("nativeTransfers") or []:
            a = bot.fnum(n.get("amount")) / 1e9 * sol_usd
            if n.get("fromUserAccount") == adres:
                quote_out += a
            if n.get("toUserAccount") == adres:
                quote_in += a

        for mint in girdi:                      # ALIM
            d = per.setdefault(mint, {"al": 0.0, "sat": 0.0, "n_al": 0, "n_sat": 0,
                                      "ilk": ts, "son": ts})
            d["al"] += quote_out
            d["n_al"] += 1
            d["ilk"] = min(d["ilk"], ts) if d["ilk"] else ts
            d["son"] = max(d["son"], ts)
        for mint in cikti:                      # SATIM
            d = per.setdefault(mint, {"al": 0.0, "sat": 0.0, "n_al": 0, "n_sat": 0,
                                      "ilk": ts, "son": ts})
            d["sat"] += quote_in
            d["n_sat"] += 1
            d["son"] = max(d["son"], ts)
    return per


def rapor_yaz(ad, adres, key, sol_usd):
    now = time.time()
    txs = islemler(adres, key)
    per = akis(txs, adres, sol_usd)
    bak = bakiyeler(adres, key)

    mintler = list(dict.fromkeys(list(per) + list(bak)))
    pairs = {}
    for i in range(0, len(mintler), 30):
        pairs.update(bot.fetch_pairs("solana", mintler[i:i + 30]))
        time.sleep(0.2)

    satirlar = []
    for mint in mintler:
        d = per.get(mint, {"al": 0.0, "sat": 0.0, "n_al": 0, "n_sat": 0, "ilk": 0, "son": 0})
        p = pairs.get(mint) or {}
        sembol = (p.get("baseToken") or {}).get("symbol") or mint[:6]
        fiyat = bot.fnum(p.get("priceUsd"))
        mc = bot.fnum(p.get("marketCap"))
        elde = bak.get(mint, 0.0) * fiyat
        # kapanmış kısmın kârı + elde kalanın değeri
        net = d["sat"] + elde - d["al"]
        satirlar.append({"sembol": sembol, "mint": mint, "al": d["al"], "sat": d["sat"],
                         "elde": elde, "net": net, "mc": mc,
                         "n_al": d["n_al"], "n_sat": d["n_sat"],
                         "ilk": d["ilk"], "son": d["son"]})

    # sadece anlamlı hareket olanlar
    aktif = [s for s in satirlar if s["al"] >= 50 or s["sat"] >= 50 or s["elde"] >= 50]
    aktif.sort(key=lambda s: -s["net"])

    kapsam_dk = 0
    if txs:
        zamanlar = [t.get("timestamp") or 0 for t in txs if t.get("timestamp")]
        if zamanlar:
            kapsam_dk = (now - min(zamanlar)) / 60

    md = [f"# Cüzdan raporu: {ad}", "",
          f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
          f"Adres: `{adres}`", "",
          "## Kapsam", "",
          f"- İncelenen işlem: **{len(txs)}**",
          f"- Kapsanan süre: son **{kapsam_dk/60:.1f} saat** ({kapsam_dk/1440:.1f} gün)",
          f"- Hareket görülen coin: **{len(aktif)}**",
          "",
          "> Bu rapor sadece yukarıdaki pencereyi kapsar. Daha eski alımlar görünmediği "
          "için, elde tutulan bir coinin maliyeti eksik olabilir; o satırlarda \"net\" "
          "olduğundan iyi görünür. Kapanmış işlemler daha güvenilirdir.", ""]

    if not aktif:
        md += ["Bu pencerede $50 üzeri anlamlı hareket yok.", ""]
        (ROOT / f"CUZDAN-{ad}.md").write_text("\n".join(md), encoding="utf-8")
        return len(txs), 0

    alimlar = [s["al"] for s in aktif if s["al"] >= 50]
    md += ["## Pozisyon büyüklüğü", "",
           f"- Medyan alım: **${statistics.median(alimlar):,.0f}**" if alimlar else "- alım yok",
           f"- En büyük alım: ${max(alimlar):,.0f}" if alimlar else "",
           f"- Toplam alım: ${sum(s['al'] for s in aktif):,.0f}",
           f"- Toplam satım: ${sum(s['sat'] for s in aktif):,.0f}",
           f"- Halen elde: ${sum(s['elde'] for s in aktif):,.0f}", ""]

    # giriş yaptığı market cap dağılımı
    kova = {"< $100K": 0, "$100K - $1M": 0, "$1M - $10M": 0, "$10M +": 0, "veri yok": 0}
    for s in aktif:
        if not s["mc"]:
            kova["veri yok"] += 1
        elif s["mc"] < 1e5:
            kova["< $100K"] += 1
        elif s["mc"] < 1e6:
            kova["$100K - $1M"] += 1
        elif s["mc"] < 1e7:
            kova["$1M - $10M"] += 1
        else:
            kova["$10M +"] += 1
    md += ["## Hangi büyüklükteki coinlerde işlem yapıyor", "",
           "| Market cap aralığı | Coin sayısı |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in kova.items() if v]
    md.append("")

    kazanan = [s for s in aktif if s["net"] > 0]
    md += ["## Sonuç özeti", "",
           f"- Artıda olan coin: **{len(kazanan)} / {len(aktif)}** "
           f"(%{len(kazanan)*100//len(aktif)})",
           f"- Toplam net: **${sum(s['net'] for s in aktif):,.0f}** "
           "(satımlar + elde kalanın değeri - alımlar)", ""]

    md += ["## Coin bazında", "",
           "| Coin | Alım $ | Satım $ | Elde kalan $ | Net $ | MC | Alım/Satım adedi |",
           "|---|---|---|---|---|---|---|"]
    for s in aktif[:40]:
        md.append(f"| {s['sembol'][:14]} | ${s['al']:,.0f} | ${s['sat']:,.0f} | "
                  f"${s['elde']:,.0f} | **${s['net']:,.0f}** | "
                  f"{bot.money(s['mc']) if s['mc'] else '-'} | {s['n_al']}/{s['n_sat']} |")
    md.append("")

    md += ["## Yorum için not", "",
           "Tek bir büyük kazanç tüm tabloyu taşıyor olabilir. Aşağıdaki iki sayıyı "
           "karşılaştır:", ""]
    if len(aktif) > 1:
        ensiz = sum(s["net"] for s in aktif[1:])
        md += [f"- Toplam net: ${sum(s['net'] for s in aktif):,.0f}",
               f"- **En iyi coini ({aktif[0]['sembol']}) hariç net: ${ensiz:,.0f}**", ""]
    md.append("")

    (ROOT / f"CUZDAN-{ad}.md").write_text("\n".join(md), encoding="utf-8")
    return len(txs), len(aktif)


def main():
    key = os.environ.get("HELIUS_API_KEY", "").strip()
    if not key:
        raise SystemExit("HELIUS_API_KEY yok")
    cfg = bot.load_config()
    sol_usd = bot.sol_fiyati()
    for w in (cfg.get("cuzdan_takip") or {}).get("cuzdanlar", []):
        n, k = rapor_yaz(w["ad"], w["adres"], key, sol_usd)
        print(f"CUZDAN-{w['ad']}.md yazildi: {n} islem, {k} coin")


if __name__ == "__main__":
    main()
