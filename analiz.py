#!/usr/bin/env python3
"""
Erken alıcı (smart money) cüzdan analizi
=======================================
Son dönemin kazanan Solana coinlerini bulur, her birinin İLK dakikalarındaki
alıcılarını zincirden çeker, birden fazla kazananda erken giren cüzdanları
listeler ve botları ayıklar.

Sonuç: cuzdanlar.json + CUZDAN-RAPORU.md (depoya yazılır)

Çalıştırma: python analiz.py    (HELIUS_API_KEY ortam değişkeni gerekir)
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

KEY = os.environ.get("HELIUS_API_KEY", "").strip()
RPC = f"https://mainnet.helius-rpc.com/?api-key={KEY}"
TX_API = f"https://api.helius.xyz/v0/transactions?api-key={KEY}"
ADDR_API = "https://api.helius.xyz/v0/addresses/{addr}/transactions"
GECKO = "https://api.geckoterminal.com/api/v2"
WSOL = "So11111111111111111111111111111111111111112"

# --- ayarlar -----------------------------------------------------------
MIN_GAIN_24H = 80          # kazanan sayılmak için 24 saatlik artış (%)
MIN_MC, MAX_MC = 3e5, 8e7  # kazanan coinin market cap aralığı
MAX_TOKENS = 8             # en fazla kaç kazanan coin incelensin
MAX_SIG_PAGES = 150        # token başına en fazla kaç sayfa imza (1000/sayfa)
EARLY_TX = 300             # her coinin ilk kaç işlemine bakılsın
EARLY_MINUTES = 45         # ilk işlemden sonraki kaç dakika "erken" sayılsın
MIN_SOL = 0.15             # bu kadar SOL'den küçük alımlar sayılmaz
MIN_TOKENS_HIT = 2         # kaç farklı kazananda çıkarsa listeye girsin

ROOT = Path(__file__).resolve().parent
session = requests.Session()
session.headers.update({"User-Agent": "fomo-bot-analiz/1.0"})


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def rpc(method, params, retries=3):
    for i in range(retries):
        try:
            r = session.post(RPC, json={"jsonrpc": "2.0", "id": 1,
                                        "method": method, "params": params}, timeout=30)
            if r.status_code == 429:
                time.sleep(2 * (i + 1))
                continue
            r.raise_for_status()
            return r.json().get("result")
        except requests.RequestException as e:
            log("RPC hata:", method, e)
            time.sleep(1.5 * (i + 1))
    return None


def get_json(url, params=None, headers=None, retries=2):
    for i in range(retries + 1):
        try:
            r = session.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                time.sleep(2 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if i == retries:
                log("HTTP hata:", url, e)
                return None
            time.sleep(1.5 * (i + 1))
    return None


# --- 1. kazanan coinleri bul -------------------------------------------
def find_winners():
    seen, out = set(), []
    for path in ("trending_pools", "pools?page=1", "new_pools"):
        data = get_json(f"{GECKO}/networks/solana/{path}",
                        headers={"Accept": "application/json;version=20230302"})
        for p in (data or {}).get("data") or []:
            a = p.get("attributes") or {}
            rel = ((p.get("relationships") or {}).get("base_token") or {}).get("data") or {}
            mint = (rel.get("id") or "").split("_")[-1]
            gain = float((a.get("price_change_percentage") or {}).get("h24") or 0)
            mc = float(a.get("market_cap_usd") or a.get("fdv_usd") or 0)
            if not mint or mint in seen or mint == WSOL:
                continue
            seen.add(mint)
            if gain >= MIN_GAIN_24H and MIN_MC <= mc <= MAX_MC:
                out.append({"mint": mint, "name": a.get("name", "?"), "gain": gain, "mc": mc})
        time.sleep(2.2)
    out.sort(key=lambda x: -x["gain"])
    return out[:MAX_TOKENS]


# --- 2. bir coinin en eski işlemleri -----------------------------------
TESHIS = []


def oldest_signatures(mint):
    """Mint hesabının imzalarını sonundan başa doğru toplar, en eskileri döndürür."""
    sigs, before = [], None
    for page in range(MAX_SIG_PAGES):
        params = [mint, {"limit": 1000}]
        if before:
            params[1]["before"] = before
        res = rpc("getSignaturesForAddress", params)
        if not res:
            break
        sigs.extend(res)
        before = res[-1]["signature"]
        if len(res) < 1000:
            TESHIS.append(f"{mint[:8]}: toplam {len(sigs)} işlem, en eskilere ulaşıldı")
            return sigs[-EARLY_TX:][::-1]  # en eskiler, eskiden yeniye
        time.sleep(0.15)
    TESHIS.append(f"{mint[:8]}: {len(sigs)}+ işlem, limit doldu - ATLANDI")
    log(f"  {mint[:8]}: çok işlemli ({len(sigs)}+), atlanıyor")
    return None


def parse_buyers(signatures, mint):
    """Parsed işlemlerden (alıcı cüzdan, harcanan SOL, zaman) çıkarır."""
    buys = []
    for i in range(0, len(signatures), 100):
        chunk = [s["signature"] for s in signatures[i:i + 100]]
        try:
            r = session.post(TX_API, json={"transactions": chunk}, timeout=45)
            if r.status_code == 429:
                time.sleep(3)
                r = session.post(TX_API, json={"transactions": chunk}, timeout=45)
            r.raise_for_status()
            txs = r.json()
        except (requests.RequestException, ValueError) as e:
            log("  parse hata:", e)
            continue
        for tx in txs or []:
            ts = tx.get("timestamp") or 0
            got = defaultdict(float)     # cüzdan -> alınan token
            paid = defaultdict(float)    # cüzdan -> harcanan SOL
            for t in tx.get("tokenTransfers") or []:
                amt = float(t.get("tokenAmount") or 0)
                if t.get("mint") == mint and t.get("toUserAccount"):
                    got[t["toUserAccount"]] += amt
                elif t.get("mint") == WSOL and t.get("fromUserAccount"):
                    paid[t["fromUserAccount"]] += amt
            for n in tx.get("nativeTransfers") or []:
                if n.get("fromUserAccount"):
                    paid[n["fromUserAccount"]] += float(n.get("amount") or 0) / 1e9
            for w, amt in got.items():
                sol = paid.get(w, 0.0)
                if amt > 0 and sol >= MIN_SOL:
                    buys.append({"wallet": w, "sol": round(sol, 3), "ts": ts})
        time.sleep(0.2)
    return buys


# --- 3. cüzdan bot mu? -------------------------------------------------
def wallet_profile(wallet):
    """Son 100 swap'ine bakarak bot olup olmadığını tahmin eder."""
    data = get_json(ADDR_API.format(addr=wallet),
                    params={"api-key": KEY, "limit": 100, "type": "SWAP"})
    if not data:
        return {"swaps": None, "span_h": None, "bot": None}
    times = sorted(t.get("timestamp") or 0 for t in data if t.get("timestamp"))
    if len(times) < 2:
        return {"swaps": len(data), "span_h": None, "bot": False}
    span_h = (times[-1] - times[0]) / 3600
    # 100 swap 2 saatten kısa sürede olduysa bot kabul et
    return {"swaps": len(data), "span_h": round(span_h, 1),
            "bot": len(data) >= 100 and span_h < 2}


# --- 4. ana akış -------------------------------------------------------
def main():
    if not KEY:
        log("HATA: HELIUS_API_KEY yok")
        raise SystemExit(1)

    winners = find_winners()
    log(f"{len(winners)} kazanan coin seçildi: " +
        ", ".join(f"{w['name']} +{w['gain']:.0f}%" for w in winners))

    hits = defaultdict(list)   # cüzdan -> [(coin, sol, dakika)]
    for w in winners:
        log(f"{w['name']} ({w['mint'][:8]}...) inceleniyor")
        sigs = oldest_signatures(w["mint"])
        if not sigs:
            continue
        buys = parse_buyers(sigs, w["mint"])
        if not buys:
            TESHIS.append(f"  {w['name']}: imza var ama alım çözümlenemedi")
            log("  erken alım bulunamadı")
            continue
        t0 = min(b["ts"] for b in buys if b["ts"]) or 0
        early = [b for b in buys if b["ts"] and (b["ts"] - t0) <= EARLY_MINUTES * 60]
        agg = defaultdict(lambda: [0.0, 1e9])
        for b in early:
            agg[b["wallet"]][0] += b["sol"]
            agg[b["wallet"]][1] = min(agg[b["wallet"]][1], (b["ts"] - t0) / 60)
        for wallet, (sol, mins) in agg.items():
            hits[wallet].append({"coin": w["name"], "sol": round(sol, 2),
                                 "dk": round(mins, 1), "gain": round(w["gain"])})
        TESHIS.append(f"  {w['name']}: {len(buys)} alım, ilk {EARLY_MINUTES} dk içinde "
                      f"{len(early)} alım / {len(agg)} cüzdan")
        log(f"  {len(early)} erken alım, {len(agg)} farklı cüzdan")

    repeat = {k: v for k, v in hits.items() if len(v) >= MIN_TOKENS_HIT}
    log(f"{len(hits)} cüzdan bulundu, {len(repeat)} tanesi birden fazla kazananda")

    rows = []
    for wallet, lst in sorted(repeat.items(), key=lambda kv: -len(kv[1]))[:40]:
        prof = wallet_profile(wallet)
        rows.append({"wallet": wallet, "coins": lst, "n": len(lst),
                     "toplam_sol": round(sum(x["sol"] for x in lst), 2), **prof})
        time.sleep(0.3)

    temiz = [r for r in rows if not r["bot"]]
    (ROOT / "cuzdanlar.json").write_text(
        json.dumps({"tarih": datetime.now(timezone.utc).isoformat(),
                    "kazananlar": winners, "cuzdanlar": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    md = ["# Erken Alıcı Cüzdan Analizi", "",
          f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC", "",
          "## İncelenen kazanan coinler", ""]
    md += [f"- {w['name']} — 24s +{w['gain']:.0f}%, MC ${w['mc']/1e6:.2f}M" for w in winners]
    md += ["", f"## Birden fazla kazananda erken giren cüzdanlar ({len(rows)})", "",
           "| Cüzdan | Kaç coin | Toplam SOL | Son 100 swap süresi | Bot? | Detay |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        det = ", ".join(f"{c['coin']} ({c['sol']} SOL, {c['dk']}. dk)" for c in r["coins"])
        md.append(f"| `{r['wallet']}` | {r['n']} | {r['toplam_sol']} | "
                  f"{r['span_h'] if r['span_h'] is not None else '?'} saat | "
                  f"{'EVET' if r['bot'] else 'hayır'} | {det} |")
    md += ["", f"Bot olmayan aday sayısı: **{len(temiz)}**", "",
           "## Teşhis", ""] + [f"- {t}" for t in TESHIS] + [""]
    (ROOT / "CUZDAN-RAPORU.md").write_text("\n".join(md), encoding="utf-8")
    log(f"Rapor yazıldı: {len(rows)} satır, {len(temiz)} bot değil")


if __name__ == "__main__":
    main()
