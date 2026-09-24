# Telegram teşhisi

Tarih: 2026-09-24 07:12 UTC

## 1. Secret'lar tanımlı mı

- `TELEGRAM_BOT_TOKEN`: TANIMLI (uzunluk 46, biçim doğru)
- `TELEGRAM_CHAT_ID`: TANIMLI (uzunluk 10, kişisel sohbet, sadece rakam)

## 2. Token geçerli mi (getMe)

- HTTP 200 — ok
- Bot kullanıcı adı: @aYsEylul_bot

## 3. Chat erişilebilir mi (getChat)

- HTTP 200 — ok
- Sohbet türü: private

## 4. Mesaj gönderilebiliyor mu (sendMessage)

- HTTP 200 — ok
- Gönderim: BAŞARILI

**Sonuç:** Telegram tarafı sorunsuz. Rapor gelmiyorsa sebep botun kendi zamanlama/state mantığında.
