# Memecoin Sinyal Botu

Her 10 dakikada bir DexScreener ve GeckoTerminal'daki yeni ve trend coinleri tarar. Filtrelerden ve güvenlik kontrolünden geçenleri Telegram'a bildirir. Her sabah 09:00'da da geçmiş sinyallerin performans raporunu gönderir.

> **Bu bot alım satım yapmaz.** Cüzdanına, private key'ine ya da paraya erişimi yoktur. Sadece bildirim gönderir, karar ve işlem tamamen sende.

## Nasıl çalışır

1. **Aday bulma:** Solana, BNB ve Base ağlarında iki kaynak taranır:
   - **DexScreener:** yeni token profilleri ve "boost" listeleri. Bunlar çoğunlukla ekibin para ödeyerek yaptığı tanıtımlar.
   - **GeckoTerminal:** trend havuzlar (en çok işlem görenler) ve yeni açılan havuzlar. Reklamsız, gerçek işlem hacmine dayalı.
   Her bildirimde coinin hangi kaynaktan geldiği yazar.
2. **Piyasa filtresi:** MC, likidite, likidite/MC oranı, hacim, yaş, 24 saatlik değişim, son 1 saatteki alış/satış dengesi.
3. **Güvenlik filtresi:**
   - Solana için RugCheck: mint/freeze yetkisi, "danger" seviyeli riskler, holder sayısı, LP kilit oranı, havuz hesapları hariç top 10 holder oranı.
   - BSC ve Base için GoPlus: honeypot, vergi, kaynak kodu, top 10 holder oranı, holder sayısı, LP kilit/yakım oranı, coini çıkaran cüzdanın payı.
4. **Puanlama ve iki aşamalı onay:** Her coine 0-100 puan verilir (hacim ivmesi, alış/satış dengesi, likidite oranı, holder tabanı, top 10 dağılımı, LP kilidi). `score_min` altındakiler elenir, 70+ olanlar "A sinyali" diye işaretlenir. Bir coin ilk geçişte hemen bildirilmez, önce izlemeye alınır; bir sonraki taramada da kriterleri sağlıyorsa bildirilir. Tek seferlik sahte hacim patlamaları böylece elenir.
5. **Bildirim:** Geçenler Telegram'a gider. Aynı coin 24 saat boyunca tekrar bildirilmez.
6. **Takip:** Bildirilen her coinin fiyatı 14 gün boyunca her taramada güncellenir, gördüğü en yüksek fiyat (zirve) kaydedilir.
7. **Günlük rapor:** Son 7 günün sinyalleri için zirve ve şimdiki durum; kaynağa, market cap aralığına, ağa ve puana göre kırılım; "her sinyale $20 koysaydım şimdi / zirvede ne olurdu" hesabı.

Tüm eşikler `config.yaml` içinde, istediğin gibi değiştirebilirsin.

---

## Kurulum (yaklaşık 15 dakika)

### 1. Telegram botunu oluştur

1. Telegram'da **@BotFather**'ı aç ve `/newbot` yaz.
2. Bota bir isim ve `_bot` ile biten bir kullanıcı adı ver.
3. BotFather sana bir **token** verecek (`123456789:AAH...` gibi). **Bu token'ı kimseyle paylaşma, sohbetlere yapıştırma.** Sadece 3. adımda GitHub'a gireceksin.
4. Yeni botunu aç ve **Start**'a bas (ya da herhangi bir mesaj yaz).
5. Tarayıcıda şu adresi aç (`<TOKEN>` yerine kendi token'ını yaz):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   Çıkan sayfada `"chat":{"id":123456789` kısmındaki sayı senin **chat ID**'n.
   Sayfa boş gelirse bota tekrar bir mesaj yaz ve sayfayı yenile.

### 2. GitHub deposunu oluştur

1. [github.com](https://github.com)'da ücretsiz bir hesap aç (varsa giriş yap).
2. Sağ üstten **+ > New repository**'e tıkla. İsim olarak örneğin `memecoin-sinyal-botu` gir.
3. Görünürlük olarak **Public** seç. Kodda gizli bilgi yok, token'lar ayrı ve şifreli saklanıyor. Public depoda Actions dakikaları sınırsız. Private depoda ücretsiz limit ayda 2.000 dakika; 10 dakikada bir çalışan bu bot o limiti aşar.
4. **Create repository**'e tıkla.
5. Açılan sayfada **uploading an existing file** linkine tıkla. Zip'ten çıkardığın klasörün **içindeki her şeyi** (`.github` klasörü dahil) sürükleyip bırak, sonra **Commit changes**'e bas.
   - `.github` klasörü gizli olduğu için görünmüyorsa: Windows'ta Gezgin'de **Görünüm > Gizli öğeler**, Mac'te Finder'da `Cmd+Shift+.`.
   - Yükledikten sonra depoda `.github/workflows/sinyal.yml` dosyasının göründüğünü kontrol et.

### 3. Telegram bilgilerini gizli olarak ekle

Depoda **Settings > Secrets and variables > Actions > New repository secret** yolunu izle ve iki secret ekle:

| Name | Secret |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather'ın verdiği token |
| `TELEGRAM_CHAT_ID` | getUpdates'ten aldığın sayı |

### 4. Test et

1. Depoda **Actions** sekmesine git. Soruyorsa **I understand my workflows, enable them**'a bas.
2. Soldan **Memecoin sinyal botu**'nu seç, **Run workflow**'a tıkla, mod olarak `test` seç ve çalıştır.
3. Telegram'a "Memecoin sinyal botu bağlandı" mesajı gelmeli.
4. Aynı yerden bir kez de `scan` modunu çalıştır. Log'da "X aday bulundu, Y bildirim gönderildi" satırlarını ve elenme sebeplerini görürsün.

Bundan sonrası otomatik: tarama her 10 dakikada bir, rapor her gün 09:00'da.

---

## Bilmen gerekenler

- **Zamanlama gecikebilir:** GitHub zamanlanmış görevleri yoğun saatlerde 5–15 dakika geç çalıştırabiliyor. Saniyeler önemli olan "snipe" işleri için uygun değil, "incelemeye değer coin" sinyali için yeterli.
- **60 gün kuralı:** Public depolarda 60 gün boyunca hiç commit olmazsa GitHub zamanlanmış görevleri durdurur. Arada `config.yaml`'da küçük bir değişiklik yapman yeterli.
- **Çok az bildirim geliyorsa:** `config.yaml`'da filtreleri gevşet. Örneğin `h1_txns_min: 15`, `liquidity_to_mc_min: 0.02`. **Çok fazla geliyorsa** sıkılaştır.
- **Log'lar:** Actions sekmesinde her çalışmaya tıklayınca hangi filtrenin kaç coini elediğini görürsün. Ayar yaparken çok işe yarar.
- **Sinyal ≠ al komutu:** Filtreler sadece bariz kötüleri eler. Geçen coinlerin de büyük kısmı düşebilir. İlk 2–3 hafta sadece izle ve günlük raporlara bak.
- **Kendi bilgisayarında denemek istersen:** `pip install -r requirements.txt`, sonra `python bot.py --mode scan --dry-run`. Bu komut Telegram'a göndermeden sonuçları ekrana yazar.
