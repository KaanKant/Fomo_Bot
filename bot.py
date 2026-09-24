#!/usr/bin/env python3
"""
Memecoin sinyal botu
====================
Herkese açık verilerle (DexScreener + GeckoTerminal + RugCheck + GoPlus) yeni/trend
low-cap coinleri tarar, filtrelerden geçenleri Telegram'a bildirir.

Bu bot ALIM SATIM YAPMAZ. Cüzdana, private key'e ya da paraya erişimi yoktur.
Sadece bildirim gönderir; karar ve işlem tamamen kullanıcıdadır.

Modlar:
  --mode scan    : tarama yap, uygun coinleri bildir (varsayılan)
  --mode report  : son günlerin sinyallerinin performans raporunu gönder
  --mode erken   : yeni doğmuş coinlerde organik erken ilgi ara (yüksek risk)
  --mode test    : Telegram bağlantısını test et
  --dry-run      : Telegram'a göndermek yerine ekrana yaz
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state" / "state.json"
CONFIG_PATH = ROOT / "config.yaml"

DEX = "https://api.dexscreener.com"
RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"
GOPLUS = "https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
GECKO = "https://api.geckoterminal.com/api/v2"
GECKO_NETWORKS = {"solana": "solana", "bsc": "bsc", "base": "base", "ethereum": "eth"}
# Havuzlarda karşı taraf olan (memecoin olmayan) tokenlar: wrapped native coinler ve stable'lar
QUOTE_TOKENS = {a.lower() for a in (
    "So11111111111111111111111111111111111111112",   # WSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC (Solana)
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT (Solana)
    "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",    # WBNB
    "0x55d398326f99059fF775485246999027B3197955",    # USDT (BSC)
    "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",    # USDC (BSC)
    "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",    # BUSD
    "0x4200000000000000000000000000000000000006",    # WETH (Base)
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",    # USDC (Base)
    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",    # WETH (Ethereum)
)}
GOPLUS_CHAIN_IDS = {"bsc": "56", "base": "8453", "ethereum": "1"}
CHAIN_LABELS = {"solana": "Solana", "bsc": "BNB Chain", "base": "Base", "ethereum": "Ethereum"}
# FOMO'daki token sayfası yolları (solana ve bnb doğrulandı)
FOMO_PATHS = {"solana": "solana", "bsc": "bnb"}

session = requests.Session()
session.headers.update({"User-Agent": "memecoin-sinyal-botu/1.0"})


# ------------------------------------------------------------------ yardımcılar
def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def get_json(url, params=None, retries=2, timeout=15, headers=None):
    for attempt in range(retries + 1):
        try:
            r = session.get(url, params=params, timeout=timeout, headers=headers)
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == retries:
                log("HATA:", url, "->", e)
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def fnum(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def money(x):
    x = fnum(x)
    if x >= 1e9:
        return f"${x/1e9:.2f}B"
    if x >= 1e6:
        return f"${x/1e6:.2f}M"
    if x >= 1e3:
        return f"${x/1e3:.1f}K"
    return f"${x:.0f}"


def age_text(hours):
    if hours < 1:
        return f"{int(hours*60)} dk"
    if hours < 48:
        return f"{hours:.0f} saat"
    return f"{hours/24:.0f} gün"


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except ValueError:
            log("state.json bozuk, sıfırdan başlıyorum")
    return {"seen": {}, "signals": []}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ Telegram
def send_telegram(text, dry_run=False):
    if dry_run:
        print("\n----- TELEGRAM (dry-run) -----\n" + text + "\n------------------------------")
        return True
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log("HATA: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID tanımlı değil")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = session.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=15,
        )
        log("Telegram yanıtı:", r.status_code, "" if r.ok else r.text[:200])
        if r.ok:
            return True
        # HTML ayrıştırma hatası tüm mesajı çöpe atıyor (örn. metinde geçen "<500K").
        # Böyle bir durumda mesaj sessizce kaybolmasın: etiketleri temizleyip düz
        # metin olarak bir kez daha dene.
        if r.status_code == 400 and "parse entities" in r.text:
            duz = re.sub(r"<[^>]+>", "", text)
            duz = html.unescape(duz)
            r2 = session.post(
                url,
                json={"chat_id": chat_id, "text": duz, "disable_web_page_preview": True},
                timeout=15,
            )
            log("Telegram düz metin yeniden deneme:", r2.status_code,
                "" if r2.ok else r2.text[:200])
            return r2.ok
        return False
    except requests.RequestException as e:
        log("Telegram hatası:", e)
        return False


# ------------------------------------------------------------------ veri toplama
def add_candidate(found, chain, addr, label):
    if chain != "solana":
        addr = addr.lower()  # EVM adresleri büyük/küçük harf duyarsız
    found.setdefault(f"{chain}:{addr}", [chain, addr, set()])[2].add(label)


def discover_dexscreener(chains, found):
    """DexScreener'ın yeni profil ve boost listeleri (çoğu ücretli tanıtım)."""
    sources = {"/token-profiles/latest/v1": "DexScreener profil",
               "/token-boosts/latest/v1": "DexScreener boost",
               "/token-boosts/top/v1": "DexScreener boost"}
    for path, label in sources.items():
        data = get_json(DEX + path) or []
        if isinstance(data, dict):
            data = [data]
        for item in data:
            chain, addr = item.get("chainId"), item.get("tokenAddress")
            if chain in chains and addr:
                add_candidate(found, chain, addr, label)


def discover_geckoterminal(chains, found):
    """GeckoTerminal trend ve yeni havuzları (işlem hacmine dayalı, reklamsız)."""
    lists = {"trending_pools": "GeckoTerminal trend", "new_pools": "GeckoTerminal yeni"}
    for chain in chains:
        network = GECKO_NETWORKS.get(chain)
        if not network:
            continue
        for path, label in lists.items():
            data = get_json(f"{GECKO}/networks/{network}/{path}",
                            headers={"Accept": "application/json;version=20230302"})
            for pool in (data or {}).get("data") or []:
                rel = pool.get("relationships") or {}
                base = (((rel.get("base_token") or {}).get("data") or {}).get("id") or "")
                quote = (((rel.get("quote_token") or {}).get("data") or {}).get("id") or "")
                # id biçimi: "<ağ>_<adres>"
                base_addr = base.split("_", 1)[1] if "_" in base else ""
                quote_addr = quote.split("_", 1)[1] if "_" in quote else ""
                addr = quote_addr if base_addr.lower() in QUOTE_TOKENS else base_addr
                if addr and addr.lower() not in QUOTE_TOKENS:
                    add_candidate(found, chain, addr, label)
            time.sleep(2.1)  # ücretsiz limit: dakikada 30 istek


def discover_candidates(cfg):
    chains = set(cfg["chains"])
    src = cfg.get("sources") or {}
    found = {}
    if src.get("dexscreener", True):
        discover_dexscreener(chains, found)
    if src.get("geckoterminal", True):
        discover_geckoterminal(chains, found)
    return [(c, a, sorted(s)) for c, a, s in found.values()]


def fetch_pairs(chain, addresses):
    """Her token için en likit çifti döndürür: {adres: pair}."""
    best = {}
    for i in range(0, len(addresses), 30):
        chunk = addresses[i:i + 30]
        data = get_json(f"{DEX}/tokens/v1/{chain}/{','.join(chunk)}") or []
        if isinstance(data, dict):
            data = data.get("pairs") or []
        for p in data:
            base = (p.get("baseToken") or {}).get("address", "")
            match = next((a for a in chunk if a.lower() == base.lower()), None)
            if not match:
                continue
            liq = fnum((p.get("liquidity") or {}).get("usd"))
            if match not in best or liq > fnum((best[match].get("liquidity") or {}).get("usd")):
                best[match] = p
    return best


def market_metrics(p, now_ms):
    txh1 = (p.get("txns") or {}).get("h1") or {}
    txh6 = (p.get("txns") or {}).get("h6") or {}
    buys, sells = int(fnum(txh1.get("buys"))), int(fnum(txh1.get("sells")))
    vol1 = fnum((p.get("volume") or {}).get("h1"))
    vol24 = fnum((p.get("volume") or {}).get("h24"))
    mc = fnum(p.get("marketCap")) or fnum(p.get("fdv"))
    liq = fnum((p.get("liquidity") or {}).get("usd"))
    created = fnum(p.get("pairCreatedAt"))
    return {
        "symbol": (p.get("baseToken") or {}).get("symbol", "?"),
        "name": (p.get("baseToken") or {}).get("name", ""),
        "price": fnum(p.get("priceUsd")),
        "mc": mc,
        "liq": liq,
        "liq_ratio": liq / mc if mc else 0.0,
        "vol24": vol24,
        "chg24": fnum((p.get("priceChange") or {}).get("h24")),
        "chg1": fnum((p.get("priceChange") or {}).get("h1")),
        "buys1": buys,
        "sells1": sells,
        "buys6": int(fnum(txh6.get("buys"))),
        "sells6": int(fnum(txh6.get("sells"))),
        "vol1": vol1,
        "vol6": fnum((p.get("volume") or {}).get("h6")),
        "chg6": fnum((p.get("priceChange") or {}).get("h6")),
        # son 1 saatlik hacim, 24 saatlik ortalamanın kaç katı (ilgi hızlanıyor mu)
        "momentum": (vol1 * 24 / vol24) if vol24 else 0.0,
        "age_h": (now_ms - created) / 3.6e6 if created else None,
        "dex_url": p.get("url", ""),
    }


def market_filter(m, cfg):
    """Geçerse None, geçmezse sebep döndürür."""
    if not (cfg["market_cap_min"] <= m["mc"] <= cfg["market_cap_max"]):
        return "MC aralık dışı"
    if m["liq"] < cfg["liquidity_min"]:
        return "likidite düşük"
    if m["liq_ratio"] < cfg["liquidity_to_mc_min"]:
        return "likidite/MC düşük"
    if m["vol24"] < cfg["volume_24h_min"]:
        return "hacim düşük"
    if m["age_h"] is None or not (cfg["age_hours_min"] <= m["age_h"] <= cfg["age_hours_max"]):
        return "yaş aralık dışı"
    if not (cfg["price_change_24h_min"] <= m["chg24"] <= cfg["price_change_24h_max"]):
        return "24s değişim aralık dışı"
    if m["buys1"] + m["sells1"] < cfg["h1_txns_min"]:
        return "işlem sayısı düşük"
    if m["buys1"] < cfg["h1_buy_sell_ratio_min"] * max(m["sells1"], 1):
        return "satış baskısı"
    if m["buys6"] + m["sells6"] > 0 and \
            m["buys6"] < cfg.get("h6_buy_sell_ratio_min", 0.9) * max(m["sells6"], 1):
        return "6 saatlik satış baskısı"
    if m["chg1"] > cfg.get("max_h1_change", 60):
        return "son 1 saatte dikey yükseliş (zirve riski)"
    # Aşırı ısınma: hacim patlamış VE fiyat zaten çok yükselmişse parti bitmiş olabilir
    if m.get("momentum", 0) >= cfg.get("overheat_momentum", 8) \
            and m["chg24"] >= cfg.get("overheat_chg24", 100):
        return "aşırı ısınmış (parabolik)"
    return None


# ------------------------------------------------------------------ güvenlik
def security_solana(mint, cfg):
    rep = get_json(RUGCHECK.format(mint=mint))
    if not rep:
        return None
    token = rep.get("token") or {}
    risks = rep.get("risks") or []
    danger = [r.get("name", "?") for r in risks if str(r.get("level", "")).lower() == "danger"]
    warn = [r.get("name", "?") for r in risks if str(r.get("level", "")).lower() == "warn"]
    holders = rep.get("totalHolders")

    # Likidite havuzu hesapları top10 holder hesabına girmemeli
    pool_accounts, lp_locked = set(), None
    for mk in rep.get("markets") or []:
        for key in ("liquidityA", "liquidityB", "pubkey"):
            if mk.get(key):
                pool_accounts.add(str(mk[key]))
        lp = mk.get("lp") or {}
        pct = lp.get("lpLockedPct")
        if isinstance(pct, (int, float)):
            lp_locked = max(lp_locked or 0.0, float(pct))
        for key in ("lpMint", "lpCurrentSupply"):
            if isinstance(lp.get(key), str):
                pool_accounts.add(lp[key])

    top = [h for h in (rep.get("topHolders") or [])
           if str(h.get("address")) not in pool_accounts and str(h.get("owner")) not in pool_accounts]
    top10 = sum(fnum(h.get("pct")) for h in top[:10]) if top else None

    res = {
        "ok": True, "reason": None,
        "holders": int(holders) if isinstance(holders, (int, float)) else None,
        "top10": top10,
        "lp_locked": lp_locked,
        "creator_pct": None,
        "summary": f"RugCheck skor {rep.get('score_normalised', rep.get('score', '?'))}",
        "flags": danger + warn,
    }
    if rep.get("rugged"):
        res.update(ok=False, reason="RugCheck: rugged")
    elif token.get("mintAuthority"):
        res.update(ok=False, reason="mint yetkisi açık")
    elif token.get("freezeAuthority"):
        res.update(ok=False, reason="freeze yetkisi açık")
    elif cfg.get("rugcheck_block_danger", True) and danger:
        res.update(ok=False, reason="RugCheck danger: " + ", ".join(danger[:3]))
    return res


BURN_ADDRESSES = {"0x000000000000000000000000000000000000dead",
                  "0x0000000000000000000000000000000000000000"}


def security_evm(chain, addr, cfg):
    chain_id = GOPLUS_CHAIN_IDS.get(chain)
    if not chain_id:
        return None
    data = get_json(GOPLUS.format(chain_id=chain_id), params={"contract_addresses": addr})
    if not data or not isinstance(data.get("result"), dict):
        return None
    info = data["result"].get(addr.lower()) or next(iter(data["result"].values()), None)
    if not info:
        return None
    holders = info.get("holders") or []
    # Kontrat adresleri (havuzlar, kilitler) hariç ilk 10 holder
    wallets = [h for h in holders
               if str(h.get("is_contract")) != "1" and str(h.get("is_locked")) != "1"]
    top10 = sum(fnum(h.get("percent")) for h in wallets[:10]) * 100

    # LP'nin ne kadarı kilitli ya da yakılmış
    lp_locked = None
    lp_holders = info.get("lp_holders") or []
    if lp_holders:
        lp_locked = sum(fnum(h.get("percent")) for h in lp_holders
                        if str(h.get("is_locked")) == "1"
                        or str(h.get("address", "")).lower() in BURN_ADDRESSES
                        or "burn" in str(h.get("tag", "")).lower()) * 100

    creator_pct = fnum(info.get("creator_percent")) * 100 if info.get("creator_percent") else None
    buy_tax = fnum(info.get("buy_tax")) * 100
    sell_tax = fnum(info.get("sell_tax")) * 100
    flags = []
    if info.get("is_mintable") == "1":
        flags.append("mintable")
    if info.get("is_open_source") == "0":
        flags.append("kaynak kodu kapalı")
    res = {
        "ok": True, "reason": None,
        "holders": int(fnum(info.get("holder_count"))) or None,
        "top10": top10 if holders else None,
        "lp_locked": lp_locked,
        "creator_pct": creator_pct,
        "summary": f"GoPlus vergi %{buy_tax:.0f}/%{sell_tax:.0f}",
        "flags": flags,
    }
    if info.get("is_honeypot") == "1" or info.get("cannot_sell_all") == "1":
        res.update(ok=False, reason="honeypot / satılamıyor")
    elif max(buy_tax, sell_tax) > cfg["max_tax_pct"]:
        res.update(ok=False, reason=f"vergi yüksek (%{max(buy_tax, sell_tax):.0f})")
    elif info.get("is_open_source") == "0":
        res.update(ok=False, reason="kontrat kaynak kodu kapalı")
    return res


def security_filter(chain, addr, cfg):
    sec = security_solana(addr, cfg) if chain == "solana" else security_evm(chain, addr, cfg)
    if sec is None:
        if cfg.get("require_security_check", True):
            return None, "güvenlik verisi alınamadı"
        return {"ok": True, "holders": None, "top10": None, "lp_locked": None,
                "creator_pct": None, "summary": "güvenlik verisi yok", "flags": []}, None
    if not sec["ok"]:
        return sec, sec["reason"]
    if sec["holders"] is not None and sec["holders"] < cfg["holders_min"]:
        return sec, "holder sayısı düşük"
    if sec["top10"] is not None and sec["top10"] > cfg["top10_max_pct"]:
        return sec, f"top10 yüksek (%{sec['top10']:.0f})"
    lp_min = cfg.get("lp_locked_min_pct")
    if lp_min and sec.get("lp_locked") is not None and sec["lp_locked"] < lp_min:
        return sec, f"LP kilitli değil (%{sec['lp_locked']:.0f})"
    cre_max = cfg.get("creator_max_pct")
    if cre_max and sec.get("creator_pct") is not None and sec["creator_pct"] > cre_max:
        return sec, f"dev cüzdanı büyük (%{sec['creator_pct']:.0f})"
    return sec, None


# ------------------------------------------------------------------ puanlama
def score_signal(m, sec, holder_growth=None):
    """0-100 arası kaba bir kalite puanı ve puanı oluşturan gerekçeler."""
    pts, why = 0, []
    mom = m.get("momentum", 0)
    if mom >= 2:
        pts += 20; why.append("hacim hızlanıyor")
    elif mom >= 1:
        pts += 12
    else:
        pts += 4
    ratio = m["buys1"] / max(m["sells1"], 1)
    if ratio >= 2:
        pts += 20; why.append("güçlü alış baskısı")
    elif ratio >= 1.5:
        pts += 14
    else:
        pts += 8
    lr = m["liq_ratio"]
    pts += 15 if lr >= 0.10 else 10 if lr >= 0.06 else 5
    h = sec.get("holders")
    if h is None:
        pts += 5
    elif h >= 2000:
        pts += 15; why.append("geniş holder tabanı")
    else:
        pts += 10 if h >= 1000 else 5
    t = sec.get("top10")
    if t is None:
        pts += 5
    elif t <= 15:
        pts += 15; why.append("dağınık holder yapısı")
    else:
        pts += 10 if t <= 25 else 5
    lp = sec.get("lp_locked")
    if lp is None:
        pts += 3
    elif lp >= 90:
        pts += 10; why.append("LP kilitli/yakılmış")
    else:
        pts += 6 if lp >= 50 else 0
    if m["age_h"] and 6 <= m["age_h"] <= 72:
        pts += 5
    if holder_growth and holder_growth > 0:
        pts += 5; why.append(f"holder +{holder_growth}")
    return min(pts, 100), why


# ------------------------------------------------------------------ izleme (iki aşamalı onay)
def confirm_stage(cfg, state, key, m, sec, now):
    """İlk geçişte izlemeye alır, ikinci geçişte onaylar.

    Dönüş: (onaylandı_mı, holder_artışı)
    """
    watch = state.setdefault("watch", {})
    prev = watch.get(key)
    growth = None
    if prev and sec.get("holders") and prev.get("holders"):
        growth = sec["holders"] - prev["holders"]
    entry = {"first_ts": (prev or {}).get("first_ts", now), "last_ts": now,
             "holders": sec.get("holders"), "price": m["price"]}
    watch[key] = entry
    if not cfg.get("confirm_signals", True):
        return True, growth
    waited = (now - entry["first_ts"]) / 60
    if waited < cfg.get("confirm_min_minutes", 15):
        return False, growth
    if waited > cfg.get("confirm_max_hours", 12) * 60:
        entry["first_ts"] = now  # çok eskidi, sayacı sıfırla
        return False, growth
    return True, growth


def prune_watch(state, now, hours=48):
    state["watch"] = {k: v for k, v in (state.get("watch") or {}).items()
                      if now - v.get("last_ts", 0) < hours * 3600}


# ------------------------------------------------------------------ sinyal takibi
def track_signals(cfg, state):
    """Açık sinyallerin güncel ve zirve fiyatını günceller."""
    now = time.time()
    keep = now - cfg.get("track_days", 14) * 86400
    sigs = [x for x in state.get("signals", []) if x["ts"] >= keep]
    if not sigs:
        return
    by_chain = {}
    for x in sigs:
        by_chain.setdefault(x["chain"], []).append(x["addr"])
    for chain, addrs in by_chain.items():
        pairs = fetch_pairs(chain, list(dict.fromkeys(addrs)))
        for x in sigs:
            if x["chain"] != chain:
                continue
            p = pairs.get(x["addr"])
            price = fnum(p.get("priceUsd")) if p else 0.0
            x["last_price"] = price
            x["last_ts"] = now
            if price > fnum(x.get("peak_price")):
                x["peak_price"] = price
                x["peak_ts"] = now
    log(f"{len(sigs)} sinyalin fiyatı güncellendi")


# ------------------------------------------------------------------ mesajlar
def links(chain, addr, dex_url):
    parts = [f'<a href="{html.escape(dex_url)}">DexScreener</a>'] if dex_url else []
    if chain in FOMO_PATHS:
        parts.append(f'<a href="https://fomo.family/tokens/{FOMO_PATHS[chain]}/{addr}">FOMO</a>')
    if chain == "solana":
        parts.append(f'<a href="https://rugcheck.xyz/tokens/{addr}">RugCheck</a>')
    elif chain in GOPLUS_CHAIN_IDS:
        parts.append(f'<a href="https://gopluslabs.io/token-security/{GOPLUS_CHAIN_IDS[chain]}/{addr}">GoPlus</a>')
    return " | ".join(parts)


def format_signal(chain, addr, m, sec, score=None, why=None):
    holders = f"{sec['holders']:,}".replace(",", ".") if sec.get("holders") else "?"
    top10 = f"%{sec['top10']:.0f}" if sec.get("top10") is not None else "?"
    lp = f"%{sec['lp_locked']:.0f}" if sec.get("lp_locked") is not None else "?"
    flags = f"\nUyarılar: {html.escape(', '.join(sec['flags'][:4]))}" if sec.get("flags") else ""
    grade = ""
    if score is not None:
        grade = f" - {'A' if score >= 70 else 'B'} sinyali ({score}/100)"
    return (
        f"<b>Yeni sinyal: {html.escape(m['symbol'])}</b>{grade} ({CHAIN_LABELS.get(chain, chain)})\n"
        f"{html.escape(m['name'])}\n\n"
        f"MC: {money(m['mc'])} | Likidite: {money(m['liq'])} (%{m['liq_ratio']*100:.1f})\n"
        f"Yaş: {age_text(m['age_h'])} | 24s hacim: {money(m['vol24'])}\n"
        f"Son 1s: {m['buys1']} alış / {m['sells1']} satış | 1s: {m['chg1']:+.0f}% | 24s: {m['chg24']:+.0f}%\n"
        f"Hacim ivmesi: {m.get('momentum', 0):.1f}x | 6s: {m['buys6']} alış / {m['sells6']} satış\n"
        f"Holder: {holders} | Top10: {top10} | LP kilitli: {lp}\n"
        f"Güvenlik: {html.escape(sec.get('summary', '?'))}{flags}\n"
        f"Artılar: {html.escape(', '.join(why) if why else '-')}\n"
        f"Kaynak: {html.escape(', '.join(m.get('sources') or ['?']))}\n\n"
        f"<code>{addr}</code>\n"
        f"{links(chain, addr, m['dex_url'])}\n\n"
        f"<i>Otomatik tarama sonucudur, yatırım tavsiyesi değildir.</i>"
    )


# ------------------------------------------------------------------ modlar
def run_scan(cfg, state, dry_run=False):
    now = time.time()
    now_ms = now * 1000
    cooldown = cfg["cooldown_hours"] * 3600
    state["seen"] = {k: t for k, t in state["seen"].items() if now - t < max(cooldown, 3 * 86400)}
    prune_watch(state, now)

    candidates = discover_candidates(cfg)
    log(f"{len(candidates)} aday bulundu")
    src_of = {f"{c}:{a}": s for c, a, s in candidates}
    by_chain = {}
    for chain, addr, _ in candidates:
        if now - state["seen"].get(f"{chain}:{addr}", 0) < cooldown:
            continue
        by_chain.setdefault(chain, []).append(addr)

    passed, reasons = [], {}
    for chain, addrs in by_chain.items():
        pairs = fetch_pairs(chain, addrs)
        for addr in addrs:
            p = pairs.get(addr)
            if not p:
                reasons["çift bulunamadı"] = reasons.get("çift bulunamadı", 0) + 1
                continue
            m = market_metrics(p, now_ms)
            why = market_filter(m, cfg)
            if why:
                reasons[why] = reasons.get(why, 0) + 1
                continue
            m["sources"] = src_of.get(f"{chain}:{addr}", [])
            passed.append((chain, addr, m))

    # En güçlü alış baskısı olanlar önce
    passed.sort(key=lambda x: x[2]["buys1"] / max(x[2]["sells1"], 1), reverse=True)
    sent, watched = 0, 0
    for chain, addr, m in passed:
        if sent >= cfg["max_alerts_per_run"]:
            break
        key = f"{chain}:{addr}"
        sec, why = security_filter(chain, addr, cfg)
        if why:
            reasons[why] = reasons.get(why, 0) + 1
            state["seen"][key] = now  # güvenlik reddi: cooldown boyunca tekrar bakma
            continue
        ok, growth = confirm_stage(cfg, state, key, m, sec, now)
        score, pros = score_signal(m, sec, growth)
        if score < cfg.get("score_min", 50):
            reasons[f"puan düşük (<{cfg.get('score_min', 50)})"] = \
                reasons.get(f"puan düşük (<{cfg.get('score_min', 50)})", 0) + 1
            continue
        if not ok:
            watched += 1
            continue
        if send_telegram(format_signal(chain, addr, m, sec, score, pros), dry_run):
            sent += 1
            state["seen"][key] = now
            state["signals"].append({
                "key": key, "chain": chain, "addr": addr, "symbol": m["symbol"],
                "price": m["price"], "peak_price": m["price"], "mc": m["mc"], "ts": now,
                "score": score, "sources": m.get("sources") or [],
            })
        time.sleep(0.5)

    keep = now - cfg.get("track_days", 14) * 86400
    state["signals"] = [x for x in state["signals"] if x["ts"] >= keep]
    track_signals(cfg, state)
    bump_stats(state, now, len(candidates), len(passed), watched, sent, reasons)
    log(f"{len(passed)} coin piyasa filtresini geçti, {sent} bildirim, {watched} izlemede")
    if reasons:
        log("Elenme sebepleri:", json.dumps(reasons, ensure_ascii=False))
    return sent


def bump_stats(state, now, candidates, passed, watched, sent, reasons):
    """Tarama istatistiklerini biriktirir; günlük raporda özetlenip sıfırlanır."""
    st = state.setdefault("stats", {"since": now, "scans": 0, "candidates": 0,
                                    "passed": 0, "watched": 0, "sent": 0, "reasons": {}})
    st["scans"] += 1
    st["candidates"] += candidates
    st["passed"] += passed
    st["watched"] += watched
    st["sent"] += sent
    for k, v in reasons.items():
        st["reasons"][k] = st["reasons"].get(k, 0) + v


def stats_summary(state, now):
    """Telegram için tarama özeti satırları; biriken istatistikleri sıfırlar."""
    st = state.get("stats")
    if not st or not st.get("scans"):
        return []
    hours = max((now - st.get("since", now)) / 3600, 0.1)
    top = sorted(st["reasons"].items(), key=lambda kv: -kv[1])[:5]
    lines = [f"\n<b>Tarama özeti - son {hours:.0f} saat</b>",
             f"{st['scans']} tarama | ortalama {st['candidates'] / st['scans']:.0f} aday",
             f"Filtreyi geçen: {st['passed']} | İzlemeye alınan: {st['watched']} | "
             f"Bildirilen: {st['sent']}"]
    if top:
        lines.append("En çok eleyen filtreler:")
        lines += [f"  {html.escape(k)}: {v}" for k, v in top]
    state["stats"] = {"since": now, "scans": 0, "candidates": 0, "passed": 0,
                      "watched": 0, "sent": 0, "reasons": {}}
    return lines


def _pct(now_price, entry):
    return (now_price / entry - 1) * 100 if entry and now_price else -100.0


def _bucket(mc):
    return "<500K" if mc < 5e5 else "500K-2M" if mc < 2e6 else "2M+"


def _summary(rows, label):
    """rows: [(sinyal, şimdiki %, zirve %)] -> tek satır özet.

    Etiket burada HTML'e göre kaçışlanır: "<500K" gibi bir etiket ham gönderilirse
    Telegram onu açılmış bir etiket sanıp TÜM mesajı reddediyor.
    """
    if not rows:
        return None
    label = html.escape(str(label))
    nowp = [r[1] for r in rows]
    peak = [r[2] for r in rows]
    hit = sum(1 for p in peak if p >= 50)
    return (f"{label}: {len(rows)} sinyal | medyan zirve {statistics.median(peak):+.0f}% | "
            f"medyan şimdi {statistics.median(nowp):+.0f}% | %50+ yapan: {hit}")


def run_report(cfg, state, dry_run=False):
    now = time.time()
    since = now - cfg["report_lookback_days"] * 86400
    sigs = [x for x in state.get("signals", []) if x["ts"] >= since and x.get("price")]
    if not sigs:
        text = "\n".join([f"<b>Günlük rapor</b>",
                          f"Son {cfg['report_lookback_days']} günde sinyal yok."]
                         + stats_summary(state, now))
        ok = send_telegram(text, dry_run)
        log(f"Rapor {'gönderildi' if ok else 'GÖNDERİLEMEDİ'} (kayıtlı sinyal yok)")
        return ok

    track_signals(cfg, state)  # rakamlar güncel olsun
    rows = [(x, _pct(fnum(x.get("last_price")), x["price"]),
             _pct(max(fnum(x.get("peak_price")), fnum(x.get("last_price"))), x["price"]))
            for x in sigs]
    rows.sort(key=lambda r: r[2], reverse=True)

    lines = [f"<b>Günlük rapor - son {cfg['report_lookback_days']} gün</b>",
             _summary(rows, "Genel")]

    # Kaynak kırılımı
    by_src = {}
    for r in rows:
        for src in (r[0].get("sources") or ["?"]):
            by_src.setdefault(src, []).append(r)
    if len(by_src) > 1:
        lines.append("\n<b>Kaynağa göre</b>")
        for src, rr in sorted(by_src.items(), key=lambda kv: -len(kv[1])):
            lines.append(_summary(rr, src))

    # Market cap kırılımı
    by_mc = {}
    for r in rows:
        by_mc.setdefault(_bucket(fnum(r[0].get("mc"))), []).append(r)
    if len(by_mc) > 1:
        lines.append("\n<b>Market cap'e göre</b>")
        for b in ("<500K", "500K-2M", "2M+"):
            if by_mc.get(b):
                lines.append(_summary(by_mc[b], b))

    # Ağ ve puan kırılımı
    by_chain = {}
    for r in rows:
        by_chain.setdefault(CHAIN_LABELS.get(r[0]["chain"], r[0]["chain"]), []).append(r)
    if len(by_chain) > 1:
        lines.append("\n<b>Ağa göre</b>")
        for c, rr in sorted(by_chain.items(), key=lambda kv: -len(kv[1])):
            lines.append(_summary(rr, c))
    graded = [r for r in rows if r[0].get("score")]
    if graded:
        a = [r for r in graded if r[0]["score"] >= 70]
        b = [r for r in graded if r[0]["score"] < 70]
        lines.append("\n<b>Puana göre</b>")
        for lbl, rr in (("A sinyalleri", a), ("B sinyalleri", b)):
            if rr:
                lines.append(_summary(rr, lbl))

    def line(r):
        x, nowp, peakp = r
        return (f"{html.escape(x['symbol'])} ({CHAIN_LABELS.get(x['chain'], x['chain'])}): "
                f"zirve {peakp:+.0f}%, şimdi {nowp:+.0f}%")

    lines.append("\n<b>En iyi</b>")
    lines += [line(r) for r in rows[:5]]
    if len(rows) > 5:
        lines.append("\n<b>En kötü</b>")
        lines += [line(r) for r in rows[max(5, len(rows) - 5):][::-1]]

    invested = 20 * len(rows)
    lines.append(f"\nHer sinyale $20: şimdi {sum(20 * (1 + r[1] / 100) for r in rows):.0f}$, "
                 f"zirvede satsaydın {sum(20 * (1 + r[2] / 100) for r in rows):.0f}$ "
                 f"(yatırılan {invested}$, ücretler hariç)")
    lines += stats_summary(state, now)
    lines += golge_ozeti(state)
    lines.append("\n<i>Zirve = sinyalden sonra görülen en yüksek fiyat (taramalar arasında "
                 "ölçüldüğü için yaklaşıktır). Fiyatı bulunamayan coinler -%100 sayılır.</i>")

    ok = send_telegram("\n".join(x for x in lines if x), dry_run)
    log(f"Rapor {'gönderildi' if ok else 'GÖNDERİLEMEDİ'} ({len(rows)} sinyal)")
    return ok


def golge_ozeti(state):
    """Günlük rapora 'veri toplama' satırı: bildirilmeyen adayların sonucu."""
    golge = state.get("golge", [])
    if not golge:
        return []
    z = []
    for g in golge:
        giris, zirve = fnum(g.get("price")), fnum(g.get("peak_price"))
        z.append((zirve / giris - 1) * 100 if giris and zirve else -100.0)
    tuttu = sum(1 for x in z if x >= 30)
    return ["\n<b>Veri toplama (bildirilmeyen adaylar)</b>",
            f"{len(golge)} kayıt | medyan zirve {statistics.median(z):+.0f}% | "
            f"+%30 gören: {tuttu}"]


def report_due(cfg, state):
    """Rapor saati geçtiyse ve bugün rapor gönderilmediyse True (Türkiye saati, UTC+3)."""
    now_tr = datetime.now(timezone.utc) + timedelta(hours=3)
    today = now_tr.strftime("%Y-%m-%d")
    return now_tr.hour >= cfg.get("report_hour", 9) and state.get("last_report") != today, today


# ------------------------------------------------------------------ erken giriş
def gecko_pools(chain, path, page=None):
    """GeckoTerminal havuz kayıtlarını ayrıntılı metriklerle döndürür."""
    network = GECKO_NETWORKS.get(chain)
    if not network:
        return []
    data = get_json(f"{GECKO}/networks/{network}/{path}",
                    params={"page": page} if page else None,
                    headers={"Accept": "application/json;version=20230302"})
    out = []
    for p in (data or {}).get("data") or []:
        a = p.get("attributes") or {}
        rel = p.get("relationships") or {}
        base = (((rel.get("base_token") or {}).get("data") or {}).get("id") or "")
        quote = (((rel.get("quote_token") or {}).get("data") or {}).get("id") or "")
        base_addr = base.split("_", 1)[1] if "_" in base else ""
        quote_addr = quote.split("_", 1)[1] if "_" in quote else ""
        addr = quote_addr if base_addr.lower() in QUOTE_TOKENS else base_addr
        if not addr or addr.lower() in QUOTE_TOKENS:
            continue
        tx = a.get("transactions") or {}
        m15 = tx.get("m15") or {}
        m5 = tx.get("m5") or {}
        created = a.get("pool_created_at") or ""
        try:
            age_min = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds() / 60
        except ValueError:
            age_min = None
        out.append({
            "chain": chain, "addr": addr, "name": (a.get("name") or "?").split(" / ")[0],
            "price": fnum(a.get("base_token_price_usd")),
            "mc": fnum(a.get("market_cap_usd")) or fnum(a.get("fdv_usd")),
            "liq": fnum(a.get("reserve_in_usd")),
            "vol1": fnum((a.get("volume_usd") or {}).get("h1")),
            "chg5": fnum((a.get("price_change_percentage") or {}).get("m5")),
            "chg1h": fnum((a.get("price_change_percentage") or {}).get("h1")),
            "buyers15": int(fnum(m15.get("buyers"))), "sellers15": int(fnum(m15.get("sellers"))),
            "buys15": int(fnum(m15.get("buys"))), "sells15": int(fnum(m15.get("sells"))),
            "buyers5": int(fnum(m5.get("buyers"))), "sellers5": int(fnum(m5.get("sellers"))),
            "age_min": age_min, "pool": a.get("address"),
            "dex": (((rel.get("dex") or {}).get("data") or {}).get("id") or ""),
        })
    time.sleep(2.1)
    return out


def insider_check(mint):
    """RugCheck'in tespit ettiği bundle/insider ağının büyüklüğü (% arz)."""
    rep = get_json(RUGCHECK.format(mint=mint))
    if not rep:
        return None
    token = rep.get("token") or {}
    nets = rep.get("insiderNetworks") or []
    insider_pct = 0.0
    supply = fnum(token.get("supply")) or 0
    for n in nets:
        if isinstance(n, dict):
            amt = fnum(n.get("tokenAmount"))
            if supply and amt:
                insider_pct += amt / supply * 100
    top_insider = sum(fnum(h.get("pct")) for h in (rep.get("topHolders") or [])
                      if h.get("insider"))
    lp_locked = None
    for mk in rep.get("markets") or []:
        pct = (mk.get("lp") or {}).get("lpLockedPct")
        if isinstance(pct, (int, float)):
            lp_locked = max(lp_locked or 0.0, float(pct))
    creator_pct = 0.0
    if supply and fnum(rep.get("creatorBalance")):
        creator_pct = fnum(rep.get("creatorBalance")) / supply * 100
    risks = [r.get("name", "?") for r in (rep.get("risks") or [])
             if str(r.get("level", "")).lower() == "danger"]
    return {
        "mint_ok": not token.get("mintAuthority") and not token.get("freezeAuthority"),
        "rugged": bool(rep.get("rugged")),
        "insider_pct": round(max(insider_pct, top_insider), 2),
        "insider_wallets": len(nets),
        "lp_locked": lp_locked,
        "creator_pct": round(creator_pct, 2),
        "holders": rep.get("totalHolders"),
        "danger": risks,
        "score": rep.get("score_normalised", rep.get("score")),
    }


def early_filter(p, e):
    """Erken giriş adayı için davranış filtresi. Geçerse None."""
    if p["age_min"] is None or not (e["age_min_minutes"] <= p["age_min"] <= e["age_max_hours"] * 60):
        return "yaş aralık dışı"
    if not (e["mc_min"] <= p["mc"] <= e["mc_max"]):
        return "MC aralık dışı"
    if p["liq"] < e["liq_min"]:
        return "likidite düşük"
    if p["mc"] and p["liq"] / p["mc"] < e["liq_to_mc_min"]:
        return "likidite/MC düşük"
    # Hacim eşiği yaşa göre ölçeklenir: 5 dakikalık coinden 1 saatlik hacim beklenemez
    gerekli_hacim = max(e.get("vol_young_min", 5000),
                        e["vol_h1_min"] * min(1.0, p["age_min"] / 60))
    if p["vol1"] < gerekli_hacim:
        return "hacim düşük"
    if p["buyers15"] < e["buyers15_min"]:
        return "alıcı sayısı az"
    if p["buyers15"] < e["buyers_sellers_min"] * max(p["sellers15"], 1):
        return "satış baskısı"
    if p["buyers5"] < 1:
        return "son 5 dk alım yok"
    return None


def format_early(p, sec):
    liq_ratio = p["liq"] / p["mc"] * 100 if p["mc"] else 0
    holders = sec.get("holders")
    return (
        f"<b>ERKEN GİRİŞ: {html.escape(p['name'])}</b> ({CHAIN_LABELS.get(p['chain'], p['chain'])})\n"
        f"<i>Yüksek risk - coin {int(p['age_min'])} dakikalık</i>\n\n"
        f"MC: {money(p['mc'])} | Likidite: {money(p['liq'])} (%{liq_ratio:.0f})\n"
        f"1s hacim: {money(p['vol1'])} | 5 dk: {p['chg5']:+.0f}% | 1s: {p['chg1h']:+.0f}%\n"
        f"Son 15 dk: <b>{p['buyers15']} farklı alıcı</b> / {p['sellers15']} satıcı "
        f"({p['buys15']} alış / {p['sells15']} satış)\n"
        f"Holder: {holders if holders else '?'} | "
        f"LP: {'launchpad bonding curve (kurucu çekemez)' if sec.get('launchpad') else ('kilitli %%%.0f' % sec['lp_locked']) if sec.get('lp_locked') is not None else '?'}\n"
        f"Insider/bundle payı: %{sec.get('insider_pct', 0):.1f} | "
        f"Dev cüzdanı: %{sec.get('creator_pct', 0):.1f}\n\n"
        f"<code>{p['addr']}</code>\n"
        f"{links(p['chain'], p['addr'], '')}\n\n"
        f"<i>Bu kategoride coinlerin çoğu sıfıra gider. Küçük pozisyon, "
        f"2x'te ana parayı çek. Yatırım tavsiyesi değildir.</i>"
    )


def golge_ekle(state, key, p, sec, now):
    """Filtreleri geçen adayı ölçümleriyle birlikte 'gölge' listesine yazar.

    Bildirim gönderilmiş olsa da olmasa da kaydedilir. Amaç ileride
    "hangi ölçüm yükselişi öngörüyor" sorusunu tahminle değil veriyle yanıtlamak.
    """
    golge = state.setdefault("golge", [])
    if any(g["key"] == key for g in golge):
        return
    golge.append({
        "key": key, "chain": p["chain"], "addr": p["addr"], "symbol": p["name"],
        "ts": now, "price": p["price"], "peak_price": p["price"], "last_price": p["price"],
        "hist": [[0, p["price"]]],
        "o": {  # ölçümler (kısa adlar: state dosyası şişmesin)
            "yas": round(p["age_min"] or 0, 1),
            "mc": round(p["mc"]), "liq": round(p["liq"]),
            "likmc": round(p["liq"] / p["mc"], 3) if p["mc"] else 0,
            "vol1": round(p["vol1"]),
            "al15": p["buyers15"], "sat15": p["sellers15"], "al5": p["buyers5"],
            "oran": round(p["buyers15"] / max(p["sellers15"], 1), 2),
            "chg5": round(p["chg5"], 1), "chg1h": round(p["chg1h"], 1),
            "dex": p.get("dex", ""), "lp": sec.get("lp_locked"),
            "insider": sec.get("insider_pct"), "dev": sec.get("creator_pct"),
            "holder": sec.get("holders"), "launchpad": bool(sec.get("launchpad")),
        },
    })


def track_golge(cfg, state):
    """Gölge kayıtlarının fiyatını günceller ve fiyat geçmişini biriktirir."""
    now = time.time()
    gun = cfg.get("erken", {}).get("golge_gun", 3)
    golge = [g for g in state.get("golge", []) if now - g["ts"] < gun * 86400]
    state["golge"] = golge[-400:]          # state dosyası sınırsız büyümesin
    golge = state["golge"]
    if not golge:
        return
    by_chain = {}
    for g in golge:
        by_chain.setdefault(g["chain"], []).append(g["addr"])
    for chain, addrs in by_chain.items():
        pairs = fetch_pairs(chain, list(dict.fromkeys(addrs)))
        for g in golge:
            if g["chain"] != chain:
                continue
            p = pairs.get(g["addr"])
            price = fnum(p.get("priceUsd")) if p else 0.0
            g["last_price"] = price
            if price > fnum(g.get("peak_price")):
                g["peak_price"] = price
            dk = int((now - g["ts"]) / 60)
            # aynı dakikaya ikinci bir nokta yazma (tarama içinde tekrar çağrılabiliyor)
            if price > 0 and len(g["hist"]) < 80 and g["hist"][-1][0] != dk:
                g["hist"].append([dk, price])
    log(f"{len(golge)} gölge kaydı güncellendi")


def run_early(cfg, state, dry_run=False):
    """Yeni doğmuş coinlerde organik erken ilgi arar (bot kümesi değil)."""
    e = cfg.get("erken") or {}
    if not e.get("aktif"):
        log("erken giriş kapalı")
        return 0
    now = time.time()
    cooldown = e.get("cooldown_hours", 12) * 3600
    seen = state.setdefault("seen_erken", {})
    state["seen_erken"] = {k: t for k, t in seen.items() if now - t < cooldown}
    seen = state["seen_erken"]

    pools, reasons = [], {}
    for chain in e.get("chains", ["solana"]):
        # new_pools'un tek sayfası Solana'da sadece son 1-2 dakikayı kapsıyor;
        # 5-60 dakikalık aralığı görebilmek için birkaç sayfa geriye gidiyoruz.
        for page in range(1, int(e.get("new_pool_pages", 8)) + 1):
            pools += gecko_pools(chain, "new_pools", page)
        pools += gecko_pools(chain, "trending_pools")
    uniq = {}
    for p in pools:
        key = f"{p['chain']}:{p['addr']}"
        if key not in uniq or p["liq"] > uniq[key]["liq"]:
            uniq[key] = p
    log(f"{len(uniq)} yeni havuz incelendi")

    adaylar = []
    for key, p in uniq.items():
        if now - seen.get(key, 0) < cooldown:
            continue
        why = early_filter(p, e)
        if why:
            reasons[why] = reasons.get(why, 0) + 1
            continue
        adaylar.append((key, p))
    adaylar.sort(key=lambda kp: -kp[1]["buyers15"])

    # Günlük tavan: bu kategori çok üretken, gün içinde taşmasın
    bugun = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    gun = state.setdefault("erken_gun", {"tarih": bugun, "adet": 0})
    if gun.get("tarih") != bugun:
        gun.update({"tarih": bugun, "adet": 0})
    kalan_gun = e.get("max_alerts_per_day", 10) - gun["adet"]

    sent = 0
    for key, p in adaylar:
        if sent >= e.get("max_alerts_per_run", 1) or sent >= kalan_gun:
            if kalan_gun <= 0:
                reasons["günlük bildirim tavanı doldu"] = len(adaylar)
            break
        if p["chain"] != "solana":          # güvenlik kontrolü şimdilik Solana
            reasons["ağ desteklenmiyor"] = reasons.get("ağ desteklenmiyor", 0) + 1
            continue
        sec = insider_check(p["addr"])
        if not sec:
            reasons["güvenlik verisi yok"] = reasons.get("güvenlik verisi yok", 0) + 1
            continue
        # Launchpad (bonding curve) havuzlarında likiditeyi program tutar; kurucu
        # çekemediği için "LP kilitli değil" uyarısı burada gerçek bir risk değil.
        dex = (p.get("dex") or "").lower()
        launchpad = any(k in dex for k in e.get("launchpad_dexes", []))
        danger = [d for d in sec["danger"]
                  if not (launchpad and "lp unlocked" in d.lower())]

        bad = None
        if sec["rugged"] or danger:
            bad = f"RugCheck riskli ({danger[0] if danger else 'rugged'})"
        elif not sec["mint_ok"]:
            bad = "mint/freeze yetkisi açık"
        # LP kilidi SADECE launchpad dışı havuzlarda aranır; aşağıdaki insider ve
        # dev cüzdanı kontrolleri her havuz için geçerlidir.
        elif not launchpad and sec["lp_locked"] is None:
            bad = "LP kilit verisi yok"      # erken kategoride şüpheden yararlandırma yok
        elif not launchpad and sec["lp_locked"] < e.get("lp_locked_min", 90):
            bad = "LP kilitli değil"
        elif sec["insider_pct"] > e.get("insider_max_pct", 15):
            bad = f"insider/bundle payı yüksek (%{sec['insider_pct']:.0f})"
        elif sec["creator_pct"] > e.get("creator_max_pct", 5):
            bad = f"dev cüzdanı büyük (%{sec['creator_pct']:.0f})"
        if bad:
            reasons[bad] = reasons.get(bad, 0) + 1
            seen[key] = now
            continue
        sec["launchpad"] = launchpad

        # Bildirim gönderilsin ya da gönderilmesin, adayı ölçümleriyle birlikte
        # kaydet. Bu kayıtlar hangi ölçümün gerçekten yükselişi öngördüğünü
        # sonradan veriyle bulmamızı sağlıyor.
        golge_ekle(state, key, p, sec, now)

        if e.get("sadece_veri"):
            reasons["sadece veri modu (bildirim kapalı)"] = \
                reasons.get("sadece veri modu (bildirim kapalı)", 0) + 1
            seen[key] = now
            time.sleep(0.5)     # RugCheck'i arka arkaya yormayalım
            continue

        if send_telegram(format_early(p, sec), dry_run):
            sent += 1
            gun["adet"] += 1
            seen[key] = now
            state.setdefault("signals", []).append({
                "key": key, "chain": p["chain"], "addr": p["addr"], "symbol": p["name"],
                "price": p["price"], "peak_price": p["price"], "mc": p["mc"], "ts": now,
                "score": None, "sources": ["Erken giriş"],
            })
        time.sleep(0.5)

    track_signals(cfg, state)
    track_golge(cfg, state)
    bump_stats(state, now, len(uniq), len(adaylar), 0, sent, reasons)
    log(f"{len(adaylar)} aday, {sent} erken giriş bildirimi, "
        f"{len(state.get('golge', []))} gölge kaydı")
    if reasons:
        log("Elenme sebepleri:", json.dumps(reasons, ensure_ascii=False))
    return sent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="scan",
                    choices=["scan", "report", "test", "erken"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if args.mode == "test":
        ok = send_telegram("Memecoin sinyal botu bağlandı. Bildirimler bu sohbete gelecek.", args.dry_run)
        sys.exit(0 if ok else 1)

    state = load_state()
    try:
        if args.mode == "erken":
            run_early(cfg, state, args.dry_run)
        elif args.mode == "scan":
            run_scan(cfg, state, args.dry_run)
            # erken giriş kategorisi aynı taramada çalışır (ayrı cron gerekmez)
            if (cfg.get("erken") or {}).get("aktif"):
                try:
                    run_early(cfg, state, args.dry_run)
                except Exception as e:  # erken hatası ana taramayı düşürmesin
                    log("Erken giriş taraması hata verdi:", e)
            # GitHub zamanlanmış çalıştırmaları bazen atlıyor; rapor saati geçtiyse
            # ve bugün rapor gitmediyse taramanın ardından raporu da gönder.
            due, today = report_due(cfg, state)
            if due and run_report(cfg, state, args.dry_run):
                state["last_report"] = today
        else:
            if run_report(cfg, state, args.dry_run):
                state["last_report"] = report_due(cfg, state)[1]
    finally:
        save_state(state)


if __name__ == "__main__":
    main()
