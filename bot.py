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
  --mode test    : Telegram bağlantısını test et
  --dry-run      : Telegram'a göndermek yerine ekrana yaz
"""
from __future__ import annotations

import argparse
import html
import json
import os
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
    try:
        r = session.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=15,
        )
        log("Telegram yanıtı:", r.status_code, "" if r.ok else r.text[:200])
        return r.ok
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
    buys, sells = int(fnum(txh1.get("buys"))), int(fnum(txh1.get("sells")))
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
        "vol24": fnum((p.get("volume") or {}).get("h24")),
        "chg24": fnum((p.get("priceChange") or {}).get("h24")),
        "chg1": fnum((p.get("priceChange") or {}).get("h1")),
        "buys1": buys,
        "sells1": sells,
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
    res = {
        "ok": True, "reason": None,
        "holders": int(holders) if isinstance(holders, (int, float)) else None,
        "top10": None,
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
        return {"ok": True, "holders": None, "top10": None, "summary": "güvenlik verisi yok",
                "flags": []}, None
    if not sec["ok"]:
        return sec, sec["reason"]
    if sec["holders"] is not None and sec["holders"] < cfg["holders_min"]:
        return sec, "holder sayısı düşük"
    if sec["top10"] is not None and sec["top10"] > cfg["top10_max_pct"]:
        return sec, f"top10 yüksek (%{sec['top10']:.0f})"
    return sec, None


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


def format_signal(chain, addr, m, sec):
    holders = f"{sec['holders']:,}".replace(",", ".") if sec.get("holders") else "?"
    top10 = f"%{sec['top10']:.0f}" if sec.get("top10") is not None else "?"
    flags = f"\nUyarılar: {html.escape(', '.join(sec['flags'][:4]))}" if sec.get("flags") else ""
    return (
        f"<b>Yeni sinyal: {html.escape(m['symbol'])}</b> ({CHAIN_LABELS.get(chain, chain)})\n"
        f"{html.escape(m['name'])}\n\n"
        f"MC: {money(m['mc'])} | Likidite: {money(m['liq'])} (%{m['liq_ratio']*100:.1f})\n"
        f"Yaş: {age_text(m['age_h'])} | 24s hacim: {money(m['vol24'])}\n"
        f"Son 1s: {m['buys1']} alış / {m['sells1']} satış | 1s: {m['chg1']:+.0f}% | 24s: {m['chg24']:+.0f}%\n"
        f"Holder: {holders} | Top10: {top10}\n"
        f"Güvenlik: {html.escape(sec.get('summary', '?'))}{flags}\n"
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
    sent = 0
    for chain, addr, m in passed:
        if sent >= cfg["max_alerts_per_run"]:
            break
        sec, why = security_filter(chain, addr, cfg)
        if why:
            reasons[why] = reasons.get(why, 0) + 1
            state["seen"][f"{chain}:{addr}"] = now  # güvenlik reddi: cooldown boyunca tekrar bakma
            continue
        if send_telegram(format_signal(chain, addr, m, sec), dry_run):
            sent += 1
            state["seen"][f"{chain}:{addr}"] = now
            state["signals"].append({
                "key": f"{chain}:{addr}", "chain": chain, "addr": addr, "symbol": m["symbol"],
                "price": m["price"], "mc": m["mc"], "ts": now,
            })
        time.sleep(0.5)

    keep = now - 30 * 86400
    state["signals"] = [s for s in state["signals"] if s["ts"] >= keep]
    log(f"{len(passed)} coin piyasa filtresini geçti, {sent} bildirim gönderildi")
    if reasons:
        log("Elenme sebepleri:", json.dumps(reasons, ensure_ascii=False))
    return sent


def run_report(cfg, state, dry_run=False):
    now = time.time()
    since = now - cfg["report_lookback_days"] * 86400
    sigs = [s for s in state["signals"] if s["ts"] >= since and s.get("price")]
    if not sigs:
        ok = send_telegram(f"<b>Günlük rapor</b>\nSon {cfg['report_lookback_days']} günde sinyal yok.", dry_run)
        log(f"Rapor {'gönderildi' if ok else 'GÖNDERİLEMEDİ'} (kayıtlı sinyal yok)")
        return ok

    by_chain = {}
    for s in sigs:
        by_chain.setdefault(s["chain"], []).append(s["addr"])
    prices = {}
    for chain, addrs in by_chain.items():
        for addr, p in fetch_pairs(chain, list(dict.fromkeys(addrs))).items():
            prices[f"{chain}:{addr}"] = fnum(p.get("priceUsd"))

    rows = []
    for s in sigs:
        cur = prices.get(s["key"])
        chg = (cur / s["price"] - 1) * 100 if cur else -100.0  # veri yoksa (çift silinmiş) -100 say
        rows.append((s, chg))
    changes = [c for _, c in rows]
    up = sum(1 for c in changes if c > 0)
    rows.sort(key=lambda x: x[1], reverse=True)

    def line(s, c):
        return f"{html.escape(s['symbol'])} ({CHAIN_LABELS.get(s['chain'], s['chain'])}): {c:+.0f}%"

    text = (
        f"<b>Günlük rapor - son {cfg['report_lookback_days']} gün</b>\n"
        f"Sinyal: {len(rows)} | Yükselen: {up} | Düşen: {sum(1 for c in changes if c < 0)}\n"
        f"Medyan değişim: {statistics.median(changes):+.0f}%\n"
        f"Her sinyale eşit $20 koyulsaydı: {sum(20 * (1 + c / 100) for c in changes):.0f}$ "
        f"(yatırılan {20 * len(rows)}$, ücretler hariç)\n\n"
        f"<b>En iyi</b>\n" + "\n".join(line(s, c) for s, c in rows[:5])
    )
    if len(rows) > 5:
        text += "\n\n<b>En kötü</b>\n" + "\n".join(line(s, c) for s, c in rows[max(5, len(rows) - 5):][::-1])
    text += "\n\n<i>Fiyatı artık bulunamayan coinler -%100 sayılır.</i>"
    ok = send_telegram(text, dry_run)
    log(f"Rapor {'gönderildi' if ok else 'GÖNDERİLEMEDİ'} ({len(rows)} sinyal)")
    return ok


def report_due(cfg, state):
    """Rapor saati geçtiyse ve bugün rapor gönderilmediyse True (Türkiye saati, UTC+3)."""
    now_tr = datetime.now(timezone.utc) + timedelta(hours=3)
    today = now_tr.strftime("%Y-%m-%d")
    return now_tr.hour >= cfg.get("report_hour", 9) and state.get("last_report") != today, today


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="scan", choices=["scan", "report", "test"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if args.mode == "test":
        ok = send_telegram("Memecoin sinyal botu bağlandı. Bildirimler bu sohbete gelecek.", args.dry_run)
        sys.exit(0 if ok else 1)

    state = load_state()
    try:
        if args.mode == "scan":
            run_scan(cfg, state, args.dry_run)
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
