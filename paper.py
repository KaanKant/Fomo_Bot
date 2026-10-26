"""
Sanal işlem (paper trading) modülü
==================================
Sinyallerden gerçek parayla değil, SANAL bakiyeyle alım satım yapar. Amaç:
canlı bir alım satım botunun kurallarını (işlem tutarı, kâr al, zarar kes,
süre limiti, günlük zarar limiti) gerçek zamanlı fiyatlarla, para riske
atmadan denemek.

Gerçekçilik için her işlemde şunlar hesaba katılır:
  - ücret (DEX + aggregator + priority fee), her yönde yüzde olarak
  - slippage: sabit taban + havuz derinliğine göre fiyat etkisi
    (işlem tutarı / havuzun bir tarafı; sabit çarpım havuzunda yaklaşık etki)
  - rug: likidite çekilirse ya da coin listeden düşerse satış yapılamaz, pozisyon sıfırlanır

Fiyatlar sadece tarama anında okunur. Kâr al / zarar kes eşiği iki tarama
arasında geçilmişse satış, eşikten değil o anda görülen fiyattan yapılır.
Gerçek bot da arada bakmıyorsa aynısını yaşar.

Bu modül de alım satım YAPMAZ: cüzdana ve paraya erişimi yoktur.
"""
from __future__ import annotations

import html
import statistics
import time
from datetime import datetime, timedelta, timezone

ZINCIR = {"solana": "Solana", "bsc": "BNB Chain", "base": "Base", "ethereum": "Ethereum"}
SEBEP = {"kar": "kâr al", "zarar": "zarar kes", "iz": "izleyen stop", "sure": "süre doldu",
         "rug": "rug / likidite yok"}


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _ayar(cfg):
    return cfg.get("sanal_islem") or {}


def kurallar(cfg, kaynak):
    """Genel çıkış kuralları, kaynağa özel ayar varsa onunla ezilmiş hali."""
    a = _ayar(cfg)
    tur = kaynak.split(":")[0].replace("ü", "u")
    r = {"kar_al_pct": a.get("kar_al_pct"), "zarar_kes_pct": a.get("zarar_kes_pct", -50),
         "iz_stop_pct": a.get("iz_stop_pct"), "max_sure_dk": a.get("max_sure_dk", 60)}
    r.update((a.get("kurallar") or {}).get(tur) or {})
    return r


def _bugun():
    return (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%d")


def durum(cfg, state):
    """state['paper'] yoksa başlangıç bakiyesiyle kurar; gün sayaçlarını yeniler."""
    a = _ayar(cfg)
    p = state.setdefault("paper", {})
    donem = int(a.get("donem", 1))
    if p and int(p.get("donem", 1)) != donem:
        # Yeni dönem: eski sonuçların özetini arşivle, sıfırdan başla
        k = p.get("kapali", [])
        state.setdefault("paper_arsiv", []).append({
            "donem": p.get("donem", 1), "baslangic": p.get("baslangic"),
            "bitis_bakiye": round(_f(p.get("bakiye")), 2), "islem": len(k),
            "net": round(sum(_f(x.get("net")) for x in k), 2)})
        state["paper"] = p = {}
    p["donem"] = donem
    p.setdefault("bakiye", _f(a.get("baslangic_bakiye"), 200))
    p.setdefault("baslangic", p["bakiye"])
    p.setdefault("acik", [])
    p.setdefault("kapali", [])
    p.setdefault("son_giris", {})
    gun = p.setdefault("gun", {})
    if gun.get("tarih") != _bugun():
        gun.update({"tarih": _bugun(), "islem": 0, "net": 0.0})
    return p


def _kayma_pct(a, usd, liq):
    """Tahmini slippage (%): sabit taban + fiyat etkisi."""
    taban = _f(a.get("slippage_taban_pct"), 1.0)
    if liq <= 0:
        return 100.0
    etki = usd / (liq / 2) * 100        # havuzun bir tarafına göre
    return min(taban + etki, 100.0)


# ------------------------------------------------------------------ giriş
def ac(cfg, state, *, key, chain, addr, symbol, price, liq, mc, kaynak, now=None,
       notify=None, log=print):
    """Bir sinyal için sanal alım açmayı dener. Açtıysa pozisyonu, açmadıysa None döndürür."""
    a = _ayar(cfg)
    if not a.get("aktif"):
        return None
    tur = kaynak.split(":")[0].replace("ü", "u")        # "cüzdan:Ad" -> "cuzdan"
    if not (a.get("kaynaklar") or {}).get(tur, True):
        return None
    now = now or time.time()
    p = durum(cfg, state)
    tutar = _f(a.get("islem_tutari"), 20)

    neden = None
    if price <= 0 or mc <= 0:
        neden = "fiyat verisi yok"
    elif liq > mc:
        neden = "bozuk fiyat okuması"
    elif any(x["key"] == key for x in p["acik"]):
        neden = "zaten açık pozisyon var"
    elif now - p["son_giris"].get(key, 0) < _f(a.get("tekrar_giris_saat"), 24) * 3600:
        neden = "bu coine yakın zamanda girildi"
    elif len(p["acik"]) >= int(a.get("max_acik_pozisyon", 5)):
        neden = "açık pozisyon sınırı dolu"
    elif p["gun"]["islem"] >= int(a.get("gunluk_max_islem", 10)):
        neden = "günlük işlem sınırı dolu"
    elif p["gun"]["net"] <= -_f(a.get("gunluk_zarar_limiti"), 60):
        neden = "günlük zarar limiti aşıldı"
    elif p["bakiye"] < tutar:
        neden = "bakiye yetersiz"
    elif liq < _f(a.get("min_likidite"), 10000):
        neden = "likidite sanal işlem için düşük"
    if neden:
        istat = p.setdefault("atlanan", {})
        istat[neden] = istat.get(neden, 0) + 1
        log(f"Sanal alım yok ({symbol}): {neden}")
        return None

    ucret = _f(a.get("ucret_pct"), 1.0)
    kayma = _kayma_pct(a, tutar, liq)
    giris_efektif = price * (1 + kayma / 100)
    miktar = tutar * (1 - ucret / 100) / giris_efektif

    poz = {
        "key": key, "chain": chain, "addr": addr, "symbol": symbol, "kaynak": kaynak,
        "ts": now, "fiyat": price, "giris_efektif": giris_efektif, "miktar": miktar,
        "tutar": tutar, "giris_kayma": round(kayma, 2), "liq": round(liq), "mc": round(mc),
        "zirve": price, "son_fiyat": price, "kayip_okuma": 0,
    }
    p["acik"].append(poz)
    p["bakiye"] -= tutar
    p["gun"]["islem"] += 1
    p["son_giris"][key] = now
    log(f"Sanal alım: {symbol} ${tutar:.0f} @ {price:.8g} (kayma %{kayma:.1f}, kaynak {kaynak})")
    if notify and _mesaj_modu(cfg) == "hepsi":
        notify(_mesaj_alim(poz))
    return poz


# ------------------------------------------------------------------ takip ve çıkış
def tick(cfg, state, fetch_pairs, notify=None, log=print, now=None):
    """Açık pozisyonların fiyatını günceller, çıkış kurallarını uygular."""
    a = _ayar(cfg)
    if not a.get("aktif"):
        return 0
    now = now or time.time()
    p = durum(cfg, state)
    if not p["acik"]:
        return 0

    by_chain = {}
    for x in p["acik"]:
        by_chain.setdefault(x["chain"], []).append(x["addr"])
    pairs = {}
    for chain, addrs in by_chain.items():
        for addr, pair in (fetch_pairs(chain, list(dict.fromkeys(addrs))) or {}).items():
            pairs[(chain, addr)] = pair

    rug_liq = _f(a.get("rug_likidite_min"), 1000)

    kapanan, kalan = 0, []
    for x in p["acik"]:
        pair = pairs.get((x["chain"], x["addr"]))
        sebep, fiyat, liq = None, 0.0, 0.0
        if not pair:
            # Tek seferlik API boşluğu olabilir; iki tarama üst üste yoksa rug say.
            x["kayip_okuma"] = x.get("kayip_okuma", 0) + 1
            if x["kayip_okuma"] >= 2:
                sebep = "rug"
        else:
            fiyat = _f(pair.get("priceUsd"))
            liq = _f((pair.get("liquidity") or {}).get("usd"))
            mc = _f(pair.get("marketCap")) or _f(pair.get("fdv"))
            if liq < rug_liq:
                sebep = "rug"
            elif fiyat <= 0 or (mc and liq > mc):
                # bozuk okuma: bu taramayı yok say
                x["kayip_okuma"] = x.get("kayip_okuma", 0) + 1
                if x["kayip_okuma"] >= 3:
                    sebep = "rug"
            else:
                x["kayip_okuma"] = 0
                x["son_fiyat"] = fiyat
                x["zirve"] = max(_f(x.get("zirve")), fiyat)
                r = kurallar(cfg, x["kaynak"])
                degisim = (fiyat / x["fiyat"] - 1) * 100
                dusus = (1 - fiyat / x["zirve"]) * 100 if x["zirve"] else 0
                if r.get("kar_al_pct") is not None and degisim >= _f(r["kar_al_pct"]):
                    sebep = "kar"
                elif r.get("zarar_kes_pct") is not None and degisim <= _f(r["zarar_kes_pct"]):
                    sebep = "zarar"
                elif r.get("iz_stop_pct") and x["zirve"] > x["fiyat"] and dusus >= _f(r["iz_stop_pct"]):
                    sebep = "iz"
                elif (now - x["ts"]) / 60 >= _f(r.get("max_sure_dk"), 60):
                    sebep = "sure"
        if sebep:
            _kapat(cfg, p, x, sebep, fiyat, liq, now, notify, log)
            kapanan += 1
        else:
            kalan.append(x)
    p["acik"] = kalan
    p["kapali"] = p["kapali"][-500:]          # state şişmesin
    p["son_giris"] = {k: t for k, t in p["son_giris"].items() if now - t < 7 * 86400}
    log(f"Sanal işlem: {len(kalan)} açık, {kapanan} kapandı, bakiye ${p['bakiye']:.2f}")
    return kapanan


def _kapat(cfg, p, x, sebep, fiyat, liq, now, notify, log):
    a = _ayar(cfg)
    if sebep == "rug" or fiyat <= 0:
        gelir = 0.0
        kayma = 100.0
    else:
        brut = x["miktar"] * fiyat
        kayma = _kayma_pct(a, brut, liq)
        gelir = brut * (1 - kayma / 100) * (1 - _f(a.get("ucret_pct"), 1.0) / 100)
    net = gelir - x["tutar"]
    x.update({
        "kapanis_ts": now, "kapanis_fiyat": fiyat, "sebep": sebep,
        "gelir": round(gelir, 4), "net": round(net, 4),
        "net_pct": round(net / x["tutar"] * 100, 1), "cikis_kayma": round(kayma, 2),
        "zirve_pct": round((_f(x.get("zirve")) / x["fiyat"] - 1) * 100, 1),
        "sure_dk": round((now - x["ts"]) / 60),
    })
    p["bakiye"] += gelir
    p["gun"]["net"] += net
    p["kapali"].append(x)
    log(f"Sanal satış: {x['symbol']} {SEBEP[sebep]}, net {net:+.2f}$ ({x['net_pct']:+.0f}%)")
    if notify and _mesaj_modu(cfg) in ("hepsi", "kapanis"):
        notify(_mesaj_satis(x, p))


# ------------------------------------------------------------------ mesajlar
def _mesaj_modu(cfg):
    return str((cfg.get("bildirimler") or {}).get("sanal_islem", "kapanis")).lower()


def _mesaj_alim(x):
    return (f"<b>SANAL ALIM: {html.escape(x['symbol'])}</b> ({ZINCIR.get(x['chain'], x['chain'])})\n"
            f"${x['tutar']:.0f} | kaynak: {html.escape(x['kaynak'])}\n"
            f"MC ${x['mc']:,.0f} | likidite ${x['liq']:,.0f} | tahmini kayma %{x['giris_kayma']:.1f}\n"
            f"<code>{x['addr']}</code>")


def _mesaj_satis(x, p):
    isaret = "+" if x["net"] >= 0 else ""
    return (f"<b>SANAL SATIŞ: {html.escape(x['symbol'])}</b> - {SEBEP[x['sebep']]}\n"
            f"Net {isaret}{x['net']:.2f}$ ({x['net_pct']:+.0f}%) | {x['sure_dk']} dk tutuldu\n"
            f"Zirve gördüğü: {x['zirve_pct']:+.0f}% | kaynak: {html.escape(x['kaynak'])}\n"
            f"Sanal nakit bakiye: ${p['bakiye']:.2f}")


# ------------------------------------------------------------------ rapor
def _ozet(rows, etiket):
    if not rows:
        return None
    net = sum(r["net"] for r in rows)
    kazanan = sum(1 for r in rows if r["net"] > 0)
    return (f"{html.escape(etiket)}: {len(rows)} işlem | net {net:+.2f}$ | "
            f"kazanan {kazanan} (%{kazanan * 100 // len(rows)}) | "
            f"medyan {statistics.median(r['net_pct'] for r in rows):+.0f}%")


def rapor_satirlari(cfg, state, now=None):
    """Günlük rapora eklenecek sanal işlem bölümü."""
    a = _ayar(cfg)
    if not a.get("aktif"):
        return []
    now = now or time.time()
    p = durum(cfg, state)
    acik_deger = sum(x["miktar"] * _f(x.get("son_fiyat")) for x in p["acik"])
    toplam = p["bakiye"] + acik_deger
    satir = ["\n<b>Sanal işlem</b>",
             f"Bakiye ${p['bakiye']:.2f} + açık pozisyonlar ~${acik_deger:.2f} = "
             f"<b>${toplam:.2f}</b> (başlangıç ${p['baslangic']:.0f}, "
             f"{(toplam / p['baslangic'] - 1) * 100:+.1f}%)"]
    son24 = [x for x in p["kapali"] if now - x["kapanis_ts"] < 86400]
    son7 = [x for x in p["kapali"] if now - x["kapanis_ts"] < 7 * 86400]
    for rows, et in ((son24, "Son 24 saat"), (son7, "Son 7 gün"), (p["kapali"], "Tümü")):
        s = _ozet(rows, et)
        if s:
            satir.append(s)
    if not p["kapali"]:
        satir.append("Henüz kapanan sanal işlem yok.")
    if son7:
        kaynaklar = {}
        for x in son7:
            kaynaklar.setdefault(x["kaynak"].split(":")[0] if not x["kaynak"].startswith("cüzdan")
                                 else x["kaynak"], []).append(x)
        if len(kaynaklar) > 1:
            satir.append("<i>Kaynağa göre (7 gün)</i>")
            satir += [_ozet(r, k) for k, r in sorted(kaynaklar.items(), key=lambda kv: -len(kv[1]))]
        sebepler = {}
        for x in son7:
            sebepler.setdefault(SEBEP[x["sebep"]], []).append(x)
        satir.append("<i>Kapanış sebebine göre (7 gün)</i>")
        satir += [_ozet(r, k) for k, r in sorted(sebepler.items(), key=lambda kv: -len(kv[1]))]
    if p.get("atlanan"):
        en = sorted(p["atlanan"].items(), key=lambda kv: -kv[1])[:3]
        satir.append("Atlanan alımlar: " + ", ".join(f"{k} ({v})" for k, v in en))
        p["atlanan"] = {}          # rapor başına sıfırla
    def kural_metni(r):
        parca = []
        if r.get("kar_al_pct") is not None:
            parca.append(f"kâr al +%{_f(r['kar_al_pct']):.0f}")
        if r.get("zarar_kes_pct") is not None:
            parca.append(f"zarar kes %{_f(r['zarar_kes_pct']):.0f}")
        if r.get("iz_stop_pct"):
            parca.append(f"zirveden -%{_f(r['iz_stop_pct']):.0f} izleyen stop")
        parca.append(f"en fazla {_f(r.get('max_sure_dk'), 60) / 60:.0f} saat")
        return ", ".join(parca)
    satir.append(f"<i>Dönem {p.get('donem', 1)} | {kural_metni(kurallar(cfg, 'genel'))} | "
                 f"işlem başı ${_f(a.get('islem_tutari'), 20):.0f}, ücret ve kayma dahil.</i>")
    for ar in state.get("paper_arsiv", [])[-2:]:
        satir.append(f"<i>Dönem {ar['donem']}: {ar['islem']} işlem, net {ar['net']:+.0f}$</i>")
    return satir
