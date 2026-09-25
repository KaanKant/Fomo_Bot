# Çıkış kuralı backtest'i

Tarih: 2026-09-25 07:18 UTC
Test edilen kayıt: **115** (gölge 115, bildirilen sinyal 0)

## Karşılaştırma tabanı

| Strateji | Ortalama getiri | Medyan | Kazanan |
|---|---|---|---|
| Hiç satma (tut) | -54.7% | -102.0% | 21/115 |
| Tam zirvede sat (imkânsız) | +61.2% | -2.0% | 37/115 |

*Gerçekçi her kural bu ikisinin arasında kalır.*

## En iyi 15 kural

| Kâr al | Zarar kes | Süre limiti | Ortalama getiri | Medyan | Kazanma oranı |
|---|---|---|---|---|---|
| +%150 | %-50 | 60 dk | **-40.3%** | -102.0% | %30 (35/115) |
| +%150 | %-70 | 60 dk | **-40.8%** | -102.0% | %30 (35/115) |
| +%150 | %-30 | 60 dk | **-40.8%** | -102.0% | %29 (34/115) |
| +%150 | yok | 60 dk | **-41.0%** | -102.0% | %30 (35/115) |
| +%150 | %-50 | 120 dk | **-41.3%** | -102.0% | %28 (33/115) |
| +%150 | %-30 | 120 dk | **-41.4%** | -102.0% | %27 (32/115) |
| +%150 | %-30 | 240 dk | **-41.5%** | -102.0% | %26 (31/115) |
| +%150 | %-30 | 720 dk | **-41.5%** | -102.0% | %26 (31/115) |
| +%150 | %-30 | 1440 dk | **-41.5%** | -102.0% | %26 (31/115) |
| +%150 | %-50 | 240 dk | **-41.5%** | -102.0% | %27 (32/115) |
| +%150 | %-50 | 720 dk | **-41.7%** | -102.0% | %27 (32/115) |
| +%150 | %-50 | 1440 dk | **-41.7%** | -102.0% | %27 (32/115) |
| +%200 | %-50 | 60 dk | **-41.8%** | -102.0% | %27 (32/115) |
| +%150 | %-70 | 120 dk | **-42.1%** | -102.0% | %28 (33/115) |
| +%150 | yok | 120 dk | **-42.2%** | -102.0% | %28 (33/115) |

## En kötü 5 kural

| Kâr al | Zarar kes | Süre limiti | Ortalama getiri |
|---|---|---|---|
| +%20 | %-70 | 1440 dk | -61.1% |
| +%20 | %-70 | 720 dk | -61.1% |
| +%20 | yok | 240 dk | -61.2% |
| +%20 | yok | 1440 dk | -61.3% |
| +%20 | yok | 720 dk | -61.3% |

## Sadece kâr al hedefinin etkisi

*(zarar kes yok, süre limiti 24 saat)*

| Kâr al | Ortalama getiri | Kazanma oranı |
|---|---|---|
| +%20 | -61.3% | %30 |
| +%30 | -58.7% | %30 |
| +%50 | -53.9% | %30 |
| +%75 | -48.7% | %30 |
| +%100 | -45.7% | %29 |
| +%150 | -42.6% | %27 |
| +%200 | -43.8% | %25 |

## Sadece süre limitinin etkisi

*(kâr al +%50, zarar kes yok)*

| Süre | Ortalama getiri | Kazanma oranı |
|---|---|---|
| 30 dk | -54.0% | %31 |
| 60 dk | -53.6% | %31 |
| 120 dk | -53.3% | %31 |
| 240 dk | -53.8% | %30 |
| 720 dk | -53.9% | %30 |
| 1440 dk | -53.9% | %30 |

## Sonuç

En iyi kural: **+%150 kâr al**, **zarar kes %-50**, **60 dakika süre limiti** → ortalama -40.3% (kazanma oranı %30)

Karşılaştırma: hiç satmasan ortalama -54.7%.

**Uyarılar:** ücret/kayma için işlem başına %2 düşüldü, gerçekte daha yüksek olabilir. Fiyatlar 10 dakikada bir ölçüldüğü için ani sıçramalar görünmüyor. Geçmişte iyi çalışan kural gelecekte çalışmayabilir.
