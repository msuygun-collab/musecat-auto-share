# MuseCat Auto Share 🐱🎮

**Yayıncılar İçin %100 Ücretsiz, Yayın Akışını Bozmayan Çoklu Platform Klip Otomasyonu**

[🇬🇧 English Documentation (README.md)](README.md)

MuseCat Auto Share, **OBS Studio + Aitum Vertical** ile canlı yayında tek tuşla aldığınız dikey (9:16) klipleri arka planda sessizce yakalar; yayın sırasında ping/drop oluşturmadan kuyruğa alır, **Google Drive**'a yedekler ve resmi ücretsiz API'lerle **YouTube Shorts**, **Instagram Reels (+ Facebook)** ve **TikTok**'a gönderir.

---

## ✨ Özellikler

- **Yayın Modu (Stream-Safe):** Oyun/yayın sırasında ekrana pencere çıkarmaz, sağ alttaki sistem tepsisinde sessizce çalışır. Klipleri kuyruğa alır; yayın bitince tek tıkla hepsini sırayla paylaşır.
- **Ayrı Google Drive Yedekleme Sekmesi:** Klipleri tarihe göre (`YYYY-AA-GG`) otomatik klasörler, aynı klibi çift kez yüklemez ve Instagram Reels için ücretsiz video linki köprüsü görevi görür.
- **Resmi Ücretsiz API Entegrasyonları:**
  - **YouTube Shorts** (`YouTube Data API v3` — otomatik `#Shorts` etiketi)
  - **Google Drive** (`Google Drive API v3` — otomatik yedekleme)
  - **Instagram Reels** (`Meta Graph API v21` — Instagram üzerinden Facebook'a otomatik paylaşım destekli)
  - **TikTok** (`Content Posting API v2` — dahili 1 tıkla Masaüstü OAuth2 girişi, Taslak/Inbox & Doğrudan modları)
- **Türkçe & İngilizce Dil Desteği:** Ayarlar sekmesinden tek tıkla dil değiştirilebilir.
- **CMD Penceresiz Kullanım & `.exe` Paketleme:** `Masaustune_Kisayol_Olustur.bat` ile CMD açılmadan masaüstü kısayolu, `build_exe.bat` ile tek dosya Windows `.exe` çıktısı üretilebilir.

---

## 🚀 Hızlı Başlangıç

1. Bilgisayarınızda **Python 3.10+** kurulu olsun (*"Add python.exe to PATH"* işaretli).
2. **`run.bat`** dosyasına çift tıklayın (ilk açılışta `.venv` ve tüm paketleri otomatik kurar).
3. CMD penceresi olmadan kullanmak için **`Masaustune_Kisayol_Olustur.bat`** dosyasını 1 kez çalıştırıp masaüstü kısayolunu oluşturun.
4. Ücretsiz API bağlantıları için **`Kurulum_Rehberi.html`** dosyasını (veya uygulama içindeki rehber butonunu) açın.

---

## 📦 Tek Dosya `.exe` Oluşturma

Başka kullanıcılarla Python gerektirmeden paylaşmak için:

```bat
build_exe.bat
```

Çıktı `dist\MuseCatAutoShare.exe` konumunda oluşur. Kişisel `data/` klasörünüz (token ve ayarlarınız) asla pakete dahil edilmez.
