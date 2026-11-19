# AutoClipShareAuto — Resmi API Kurulum Rehberi (Ücretsiz)

Bu rehber, **AutoClipShareAuto** uygulamasının tamamen **ücretsiz ve resmi API'ler** üzerinden çalışması için gereken kimlik bilgilerini (credentials) adım adım nasıl alacağınızı anlatır.

> **İpucu:** Henüz API anahtarlarınızı hazırlamadıysanız, uygulama içindeki **Test Modu (Dry-Run)** açıkken tüm akışı (OBS klasör izleme, kuyruk, simüle yükleme) gerçek hesaplarınıza dokunmadan deneyebilirsiniz.

---

## 1. Google Cloud Kurulumu (Tek Seferde Hem YouTube Shorts Hem Google Drive)

AutoClipShareAuto, **YouTube Data API v3** ve **Google Drive API v3** için aynı Google OAuth2 oturumunu kullanır. Yani Google ile **yalnızca 1 kez** giriş yapmanız hem YouTube Shorts hem de Google Drive yedeklemesi için yeterlidir.

### Adım 1.1 — Yeni Proje Oluşturma
1. [Google Cloud Console](https://console.cloud.google.com/) adresine gidin ve Google hesabınızla giriş yapın.
2. Üst menüdeki proje seçiciden **Yeni Proje (New Project)** seçeneğine tıklayın.
3. Proje adı olarak `AutoClipShareAuto` yazın ve **Oluştur (Create)** butonuna basın.
4. Üst menüden oluşturduğunuz `AutoClipShareAuto` projesini seçin.

### Adım 1.2 — İki API'yi Etkinleştirme
1. Sol menüden **API'ler ve Hizmetler → Kitaplık (APIs & Services → Library)** bölümüne gidin.
2. Arama kutusuna **`YouTube Data API v3`** yazın, tıklayın ve **Etkinleştir (Enable)** butonuna basın.
3. Tekrar Kitaplık'a dönüp **`Google Drive API`** arayın, tıklayın ve **Etkinleştir (Enable)** butonuna basın.

### Adım 1.3 — OAuth İzin Ekranı (OAuth Consent Screen)
1. Sol menüden **API'ler ve Hizmetler → OAuth izin ekranı (OAuth consent screen)** (veya yeni arayüzde *Google Auth Platform → Branding / Audience*) bölümüne gidin.
2. Kullanıcı türü olarak **Harici (External)** seçip **Oluştur**'a tıklayın.
3. Uygulama adı olarak `AutoClipShareAuto`, destek e-postası ve geliştirici e-postası olarak kendi Gmail adresinizi girin.
4. **Kapsamlar (Scopes)** adımında (isteğe bağlı olarak) şu iki kapsamı ekleyebilirsiniz:
   - `https://www.googleapis.com/auth/youtube.upload`
   - `https://www.googleapis.com/auth/drive.file`
5. **Test Kullanıcıları (Test users)** bölümüne **kendi Gmail adresinizi** mutlaka ekleyin (uygulama "Testing" modundayken yalnızca burada ekli hesaplar giriş yapabilir).
6. Kaydedip bitirin.

### Adım 1.4 — Masaüstü Uygulaması Kimliği (`client_secret.json`) İndirme
1. Sol menüden **Kimlik Bilgileri (Credentials)** bölümüne gidin.
2. Üstteki **+ Kimlik Bilgisi Oluştur (+ Create Credentials) → OAuth istemci kimliği (OAuth client ID)** seçeneğine tıklayın.
3. Uygulama türü olarak **Masaüstü uygulaması (Desktop app)** seçin, isim olarak `AutoClipShareAuto Desktop` verin ve **Oluştur**'a basın.
4. Açılan pencerede **JSON İndir (Download JSON)** butonuna tıklayın.
5. İndirilen dosyanın adını `google_client_secret.json` yapın ve proje klasörünüzün içine kopyalayın:
   ```text
   data/credentials/google_client_secret.json
   ```
6. Uygulamada **Ayarlar → Bağlantıyı Test Et** butonuna bastığınızda tarayıcı açılacak, Google hesabınızla onay verdikten sonra oturum otomatik olarak `data/credentials/google_token.json` dosyasına kaydedilecektir.

---

## 2. Instagram Reels Kurulumu (Meta for Developers)

Meta'nın resmi Instagram Graph API'si yalnızca **İşletme (Business)** veya **İçerik Üreticisi (Creator)** hesaplarını destekler ve bir Facebook Sayfasına bağlı olmasını gerektirir.

### Adım 2.1 — Instagram Hesabını Hazırlama
1. Instagram mobil uygulamasında **Ayarlar → Hesap türü ve araçları → Profesyonel hesaba geç** yolunu izleyerek hesabınızı **İçerik Üreticisi** veya **İşletme** yapın (ücretsizdir).
2. Bir Facebook Sayfanız yoksa ücretsiz bir Facebook Sayfası oluşturun.
3. Facebook Sayfanızın **Ayarlar → Bağlı Hesaplar → Instagram** bölümünden Instagram hesabınızı bu sayfaya bağlayın.

### Adım 2.2 — Meta Uygulaması Oluşturma
1. [Meta for Developers](https://developers.facebook.com/) adresine gidin ve giriş yapın.
2. **Uygulamalarım (My Apps) → Uygulama Oluştur (Create App)** butonuna tıklayın.
3. Kullanım alanı olarak **Diğer (Other)** → Uygulama türü olarak **İşletme (Business)** seçin.
4. Uygulama adına `AutoClipShareAuto` yazıp oluşturun.
5. Uygulama panelinde **Instagram Graph API** ürününü ekleyin.

### Adım 2.3 — Access Token ve Instagram Account ID Alma
1. [Graph API Explorer](https://developers.facebook.com/tools/explorer/) aracını açın.
2. Sağ üstten oluşturduğunuz `AutoClipShareAuto` uygulamasını seçin.
3. **Kullanıcı veya Sayfa (User or Page)** alanından **User Token** seçin ve şu izinleri ekleyin:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_show_list`
   - `pages_read_engagement`
4. **Generate Access Token** butonuna basıp Facebook/Instagram hesabınızla onaylayın.
5. **Instagram Account ID** değerini bulmak için Graph API Explorer sorgu kutusuna şunu yazıp **Submit** deyin:
   ```text
   me/accounts?fields=name,instagram_business_account
   ```
   Dönen yanıttaki `instagram_business_account.id` değeri sizin **Instagram Account ID** numaranızdır.
6. Kısa ömürlü token'ı 60 günlük uzun ömürlü token'a çevirmek için [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) sayfasına token'ı yapıştırıp en alttaki **Extend Access Token** butonuna tıklayabilirsiniz.
7. Aldığınız **Access Token** ve **Instagram Account ID** bilgilerini AutoClipShareAuto **Ayarlar** ekranına girin.

> **Facebook İpucu:** Instagram mobil uygulamasında *Ayarlar → Paylaşım ve remiksler → Facebook'ta otomatik paylaş* seçeneğini açarsanız, MuseCat Auto Share ile Instagram'a yüklenen her Reels otomatik olarak Facebook sayfanızda da paylaşılır.

### Adım 2.4 — Instagram İçin Ücretsiz Herkese Açık Video Linki
Instagram Graph API, videoyu doğrudan bilgisayardan değil, herkese açık bir HTTP/HTTPS URL'sinden çeker.
- **Önerilen Ücretsiz Yöntem (Google Drive):** Paylaşım sırasında hem **Google Drive** hem **Instagram** kutucuğunu işaretli bırakın (veya Instagram URL modunu `google_drive` seçin). Program videoyu önce Drive'a yükler, yalnızca o dosya için okuma bağlantısı oluşturur ve Instagram'a otomatik iletir.
- **Alternatif Yöntem (Özel URL):** Kendi sunucunuz veya Cloudflare R2 / S3 gibi bir alanınız varsa `instagram_custom_base_url` alanına taban URL'yi girebilirsiniz.

---

## 3. TikTok Kurulumu (TikTok for Developers)

TikTok, resmi **Content Posting API v2** ile iki farklı gönderim modu sunar:

| Mod | Açıklama | Onay (Audit) Gerekir mi? |
| :--- | :--- | :--- |
| **`inbox` (Önerilen / Varsayılan)** | Video doğrudan TikTok **Taslaklar / Gelen Kutusu** bölümüne düşer; telefondan bildirimle tek dokunuşta yayınlarsınız. | **Hayır** — Ücretsiz denetlenmemiş uygulamalarda hemen çalışır. |
| **`direct`** | Video doğrudan profilinizde herkese açık olarak yayınlanır. | **Evet** — TikTok uygulama incelemesi (Audit) onayı gerekir (onay öncesi yalnızca gizli hesaplara gönderilebilir). |

### Adım 3.1 — TikTok Uygulaması Oluşturma
1. [TikTok for Developers](https://developers.tiktok.com/) portalına giriş yapın.
2. **Manage Apps → Connect an App** butonuna tıklayın ve uygulama adı olarak `AutoClipShareAuto` girin.
3. Uygulama ayarlarından **Add Products** bölümüne gidip **Content Posting API** ürününü ekleyin.
4. **Scopes** bölümünde şu izinlerin seçili olduğundan emin olun:
   - `video.upload` (Inbox / Taslak modu için yeterlidir)
   - `video.publish` (Direct / Doğrudan yayın modu için gerekir)
5. Redirect URI olarak yerel bir adres (ör. `http://localhost:8080/callback`) ekleyip kaydedin.
6. Uygulama panelinden **Client Key** ve **Client Secret** bilgilerinizi kopyalayın.
7. TikTok OAuth2 akışı ile aldığınız **Access Token** bilgisini (ve Client Key / Secret değerlerini) AutoClipShareAuto **Ayarlar** ekranına girin.
8. TikTok gönderim modunu başlangıçta **`inbox`** olarak bırakmanız önerilir.

---

## 4. OBS Studio + Aitum Vertical Klasör Ayarı

AutoClipShareAuto, bilgisayarınızda seçtiğiniz bir klip klasörünü arka planda otomatik izler ve yeni bir dikey klip kaydedildiği anda paylaşım kuyruğuna ekler.

### Adım 4.1 — Aitum Vertical Eklentisinde Kayıt Klasörünü Ayarlama
1. OBS Studio'yu açın ve **Aitum Vertical** eklentisinin ayarlar (dişli çark) simgesine tıklayın.
2. **Backtrack (Geriye Dönük Kayıt)** veya **Recording (Kayıt)** sekmesine gidin.
3. **Kayıt Yolu (Recording Path)** olarak kolay erişilebilir sabit bir klasör seçin. Örneğin:
   ```text
   C:\Users\<KullanıcıAdınız>\Videos\AitumClips
   ```
4. Video formatının **MP4** (veya OBS remux sonrası otomatik MP4) olmasına dikkat edin.
5. **Backtrack** için kısayol tuşu atayın (ör. `F9` veya Stream Deck tuşu). Oyun içinde güzel bir an olduğunda bu tuşa bastığınızda dikey klip otomatik olarak bu klasöre kaydedilir.

### Adım 4.2 — Klasörü AutoClipShareAuto'ya Tanıtma
1. AutoClipShareAuto uygulamasını açın.
2. **Ayarlar** sekmesine gidin ve **İzlenen Klip Klasörü (Watch Folder)** alanına OBS/Aitum Vertical'da belirlediğiniz klasörü seçin (`C:\Users\<KullanıcıAdınız>\Videos\AitumClips`).
3. Varsayılan başlık, açıklama ve hashtag şablonunuzu ayarlayın.
4. **Kaydet**'e basın ve ana ekrandan **İzlemeyi Başlat** butonuna tıklayın.

---

## İlk Test İçin Önerilen Sıra

1. Ayarlar'da **Test Modu (Dry-Run)** seçeneğini **Açık** bırakın.
2. OBS'ten bir test klibi alın veya izlenen klasöre küçük bir `.mp4` dosyası kopyalayın.
3. Klibin otomatik olarak algılandığını, kuyruğa eklendiğini ve simüle yüklemelerin başarıyla tamamlandığını doğrulayın.
4. API anahtarlarınızı girdikten sonra her platform için **Bağlantıyı Test Et** butonuna basın.
5. Tüm testler yeşil olduğunda **Test Modu (Dry-Run)** seçeneğini kapatıp gerçek otomatik paylaşıma geçebilirsiniz!
