# Günlük rapor teşhisi

Tarih: 2026-09-24 07:15 UTC

- state.json bulundu mu: True
- state'teki sinyal sayısı: 42
- state'teki son rapor tarihi (last_report): 2026-09-23
- izlemedeki coin sayısı: 17
- bugünün tarihi (TR): 2026-09-24
- rapor saati geldi mi / bugün gönderilmemiş mi: True

## Üretilen rapor

- karakter sayısı: **1838** (Telegram sınırı 4096)
- satır sayısı: 41

## Telegram cevabı

- HTTP 400
- ok: False
- açıklama: Bad Request: can't parse entities: Unsupported start tag "500k:" at byte offset 648

**Sonuç:** rapor Telegram tarafından reddedildi, sebebi yukarıda.

## Raporun ilk 1500 karakteri

```
<b>Günlük rapor - son 7 gün</b>
Genel: 42 sinyal | medyan zirve +0% | medyan şimdi -70% | %50+ yapan: 0

<b>Kaynağa göre</b>
Erken giriş: 20 sinyal | medyan zirve +0% | medyan şimdi -100% | %50+ yapan: 0
DexScreener boost: 8 sinyal | medyan zirve +18% | medyan şimdi -4% | %50+ yapan: 0
GeckoTerminal trend: 7 sinyal | medyan zirve +14% | medyan şimdi -5% | %50+ yapan: 0
?: 7 sinyal | medyan zirve -9% | medyan şimdi -44% | %50+ yapan: 0
DexScreener profil: 3 sinyal | medyan zirve +9% | medyan şimdi -46% | %50+ yapan: 0
GeckoTerminal yeni: 1 sinyal | medyan zirve +14% | medyan şimdi +14% | %50+ yapan: 0

<b>Market cap'e göre</b>
<500K: 33 sinyal | medyan zirve +0% | medyan şimdi -83% | %50+ yapan: 0
500K-2M: 6 sinyal | medyan zirve +0% | medyan şimdi -100% | %50+ yapan: 0
2M+: 3 sinyal | medyan zirve +3% | medyan şimdi -28% | %50+ yapan: 0

<b>Ağa göre</b>
Solana: 39 sinyal | medyan zirve +0% | medyan şimdi -85% | %50+ yapan: 0
BNB Chain: 3 sinyal | medyan zirve +3% | medyan şimdi -5% | %50+ yapan: 0

<b>Puana göre</b>
A sinyalleri: 8 sinyal | medyan zirve +17% | medyan şimdi -4% | %50+ yapan: 0
B sinyalleri: 7 sinyal | medyan zirve +3% | medyan şimdi -7% | %50+ yapan: 0

<b>En iyi</b>
Claude (Solana): zirve +49%, şimdi -100%
BLUF (Solana): zirve +39%, şimdi +26%
based (Solana): zirve +33%, şimdi -85%
UPTOBER (Solana): zirve +23%, şimdi +18%
DCA (BNB Chain): zirve +22%, şimdi -3%

<b>En kötü</b>
币安中秋 (BNB Chain): zirve -57%, şimdi -83%
XRP (Solana): zirve -37%, şimdi -53%
ㅤ (Sol
```
