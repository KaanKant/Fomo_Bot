#!/usr/bin/env python3
"""
Günlük rapor teşhisi
====================
Raporu normal yoldan üretir ama göndermeden önce araya girer: mesajın uzunluğunu,
state'te kaç sinyal olduğunu ve Telegram'ın verdiği cevabı RAPOR-TANI.md'ye yazar.

GÜVENLİK: token/chat ID dosyaya yazılmaz.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import requests

import bot

ROOT = Path(__file__).resolve().parent
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def main():
    cfg = bot.load_config()
    state = bot.load_state()
    md = ["# Günlük rapor teşhisi", "",
          f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC", "",
          f"- state.json bulundu mu: {bot.STATE_PATH.exists()}",
          f"- state'teki sinyal sayısı: {len(state.get('signals', []))}",
          f"- state'teki son rapor tarihi (last_report): {state.get('last_report', 'YOK')}",
          f"- izlemedeki coin sayısı: {len(state.get('watch', {}))}"]
    due, today = bot.report_due(cfg, state)
    md += [f"- bugünün tarihi (TR): {today}",
           f"- rapor saati geldi mi / bugün gönderilmemiş mi: {due}", ""]

    # Raporu üret ama gönderme: send_telegram'ı yakala
    yakalanan = {}

    def sahte_gonder(text, dry_run=False):
        yakalanan["text"] = text
        return True

    gercek = bot.send_telegram
    bot.send_telegram = sahte_gonder
    try:
        bot.run_report(cfg, state)
    finally:
        bot.send_telegram = gercek

    text = yakalanan.get("text", "")
    md += ["## Üretilen rapor", "",
           f"- karakter sayısı: **{len(text)}** (Telegram sınırı 4096)",
           f"- satır sayısı: {len(text.splitlines())}", ""]

    # Şimdi gerçekten gönder ve Telegram'ın cevabını kaydet
    if TOKEN and CHAT and text:
        try:
            r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                              json={"chat_id": CHAT, "text": text, "parse_mode": "HTML",
                                    "disable_web_page_preview": True}, timeout=20)
            d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            md += ["## Telegram cevabı", "",
                   f"- HTTP {r.status_code}",
                   f"- ok: {d.get('ok')}",
                   f"- açıklama: {d.get('description', '-')}", ""]
            if not d.get("ok"):
                md += ["**Sonuç:** rapor Telegram tarafından reddedildi, sebebi yukarıda.", ""]
            else:
                md += ["**Sonuç:** rapor başarıyla gönderildi.", ""]
        except requests.RequestException as e:
            md += ["## Telegram cevabı", "", f"- bağlantı hatası: {type(e).__name__}", ""]
    else:
        md += ["## Telegram cevabı", "", "- gönderilmedi (secret yok ya da rapor boş)", ""]

    md += ["## Raporun ilk 1500 karakteri", "", "```", text[:1500], "```", ""]
    (ROOT / "RAPOR-TANI.md").write_text("\n".join(md), encoding="utf-8")
    print(f"RAPOR-TANI.md yazildi ({len(text)} karakter)")


if __name__ == "__main__":
    main()
