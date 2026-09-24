#!/usr/bin/env python3
"""
Telegram bağlantı teşhisi
=========================
Bot token'ı ve chat ID'nin çalışıp çalışmadığını adım adım kontrol eder ve
sonucu TELEGRAM-TANI.md dosyasına yazar.

GÜVENLİK: token ve chat ID hiçbir zaman dosyaya yazılmaz; sadece "tanımlı mı",
uzunluk ve biçim bilgisi yazılır. Depo herkese açık olduğu için bu önemli.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
API = "https://api.telegram.org/bot{t}/{m}"


def cagir(method, payload=None):
    """Telegram API çağrısı; token'ı asla döndürmez."""
    try:
        r = requests.post(API.format(t=TOKEN, m=method), json=payload or {}, timeout=20)
        try:
            d = r.json()
        except ValueError:
            return r.status_code, "yanıt JSON değil", {}
        return r.status_code, d.get("description", "ok" if d.get("ok") else "?"), d
    except requests.RequestException as e:
        return None, f"bağlantı hatası: {type(e).__name__}", {}


def main():
    md = ["# Telegram teşhisi", "",
          f"Tarih: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC", "",
          "## 1. Secret'lar tanımlı mı", ""]

    bicim_ok = bool(re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", TOKEN))
    md += [f"- `TELEGRAM_BOT_TOKEN`: {'TANIMLI' if TOKEN else 'BOŞ / TANIMSIZ'} "
           f"(uzunluk {len(TOKEN)}, biçim {'doğru' if bicim_ok else 'HATALI'})",
           f"- `TELEGRAM_CHAT_ID`: {'TANIMLI' if CHAT else 'BOŞ / TANIMSIZ'} "
           f"(uzunluk {len(CHAT)}, {'grup/kanal (- ile başlıyor)' if CHAT.startswith('-') else 'kişisel sohbet'}, "
           f"{'sadece rakam' if CHAT.lstrip('-').isdigit() else 'RAKAM DEĞİL - hatalı olabilir'})"]

    if not TOKEN or not CHAT:
        md += ["", "**Sonuç:** secret eksik. GitHub > Settings > Secrets and variables > "
               "Actions altında adların tam olarak `TELEGRAM_BOT_TOKEN` ve "
               "`TELEGRAM_CHAT_ID` olduğunu kontrol et.", ""]
        (ROOT / "TELEGRAM-TANI.md").write_text("\n".join(md), encoding="utf-8")
        print("Secret eksik")
        return

    md += ["", "## 2. Token geçerli mi (getMe)", ""]
    kod, aciklama, d = cagir("getMe")
    bot_adi = ((d.get("result") or {}).get("username") or "?") if d.get("ok") else "-"
    md += [f"- HTTP {kod} — {aciklama}", f"- Bot kullanıcı adı: @{bot_adi}"]
    if not d.get("ok"):
        md += ["", "**Sonuç:** token geçersiz veya iptal edilmiş. BotFather'dan yeni token "
               "alıp GitHub secret'ını güncellemen gerekiyor.", ""]
        (ROOT / "TELEGRAM-TANI.md").write_text("\n".join(md), encoding="utf-8")
        print("Token gecersiz")
        return

    md += ["", "## 3. Chat erişilebilir mi (getChat)", ""]
    kod, aciklama, d = cagir("getChat", {"chat_id": CHAT})
    tur = ((d.get("result") or {}).get("type") or "?") if d.get("ok") else "-"
    md += [f"- HTTP {kod} — {aciklama}", f"- Sohbet türü: {tur}"]

    md += ["", "## 4. Mesaj gönderilebiliyor mu (sendMessage)", ""]
    kod, aciklama, d = cagir("sendMessage", {
        "chat_id": CHAT,
        "text": "<b>Teşhis mesajı</b>\nBu mesajı görüyorsan Telegram bağlantısı çalışıyor.",
        "parse_mode": "HTML", "disable_web_page_preview": True})
    md += [f"- HTTP {kod} — {aciklama}",
           f"- Gönderim: {'BAŞARILI' if d.get('ok') else 'BAŞARISIZ'}"]

    if d.get("ok"):
        md += ["", "**Sonuç:** Telegram tarafı sorunsuz. Rapor gelmiyorsa sebep botun "
               "kendi zamanlama/state mantığında.", ""]
    else:
        metin = (aciklama or "").lower()
        ipuclari = [
            ("chat not found", "Chat ID yanlış ya da bot o sohbete hiç eklenmemiş. "
                               "Bota Telegram'dan /start yazıp chat ID'yi yeniden al."),
            ("blocked by the user", "Botu Telegram'da engellemişsin; engeli kaldır."),
            ("can't initiate conversation", "Bota önce sen /start yazmalısın."),
            ("chat_id is empty", "Chat ID boş geliyor."),
            ("kicked", "Bot o gruptan atılmış; tekrar ekle."),
            ("not enough rights", "Botun o gruba mesaj atma yetkisi yok."),
        ]
        ipucu = next((v for k, v in ipuclari if k in metin),
                     "Yukarıdaki açıklamaya göre chat ID veya bot izinleri kontrol edilmeli.")
        md += ["", f"**Sonuç:** mesaj gönderilemiyor. {ipucu}", ""]

    (ROOT / "TELEGRAM-TANI.md").write_text("\n".join(md), encoding="utf-8")
    print("TELEGRAM-TANI.md yazildi")


if __name__ == "__main__":
    main()
