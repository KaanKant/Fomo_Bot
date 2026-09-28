# Deployer geçmişi teşhisi

Tarih: 2026-09-28 06:57 UTC
İncelenen coin: 15

> Bu rapor bilerek adres ve token adı yazmaz; sadece alanın yapısını gösterir. Amaç `creatorTokens` filtresini doğru alan adlarıyla yazmak.

## Alanın tipi

| Tip | Kaç coinde |
|---|---|
| null | 14 |
| liste | 1 |
| (rapor alınamadı) | 0 |

## Kurucunun kaç eski tokenı geliyor

- Kayıt sayısı: 1 coin
- En az: 39 | Medyan: 39 | En çok: 39
- Boş gelen (0 token): 0

## Her kaydın içindeki alanlar

| Alan | Kaç kez | Tip(ler) |
|---|---|---|
| `mint` | 39 | metin |
| `marketCap` | 39 | sayı |
| `createdAt` | 39 | metin |

## Sayısal alanların dağılımı

| Alan | Adet | En düşük | Medyan | En yüksek |
|---|---|---|---|---|
| `marketCap` | 39 | 2,881.62 | 5,219.73 | 26,708.27 |

## Sonraki adım

Alan adları netleştiyse `bot.py` içindeki `insider_check` bu alanı okuyup iki sayı üretecek: kurucunun kaç eski tokenı var ve kaçı ölmüş. Bu iki sayı önce sadece gölge kaydına yazılacak, hiçbir adayı elemeyecek.
