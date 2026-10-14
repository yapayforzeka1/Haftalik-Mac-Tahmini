# Teslim durumu — v3

Uygulama ve yerel doğrulama tamamlandı. Canlıya alınmadı.

- 6/5/3/2/0 puanlama; 90 dakika + hakem ek süresi.
- Resmi/tahmini XI ayrımı; kadro araştırması ve kaynak kayıtları.
- Başarılı modellerden salt çoğunluk; üç Telegram mesaj biçimi.
- Süreli, önbellekli ve kısmen eşzamanlı sağlayıcı çağrıları.
- İstatistiksel yedek tahmin; veri yoksa açık bildirim.
- Atomik kayıt ve parçalı gönderim makbuzları; kaldığı yerden devam.
- Veri/faktör kullanımı ve gol sapması analizi; geçmişten öğrenme özeti.
- Telegram admin onaylı sınırlı politika deneyleri ve geri dönüş önerisi.
- Eski puan/arşiv yedeği; eski haftalık rapor gönderimi ana akıştan çıkarıldı.
- GitHub workflow: operasyon secrets, sabit bağımlılıklar, testler,
  hata olsa da durum kaydı ve kurtarma artifact'i.

Doğrulama: 55 test geçti; Python dosyalarının sözdizimi ve workflow YAML yapısı
kontrol edildi; bir maç görseli üretildi ve incelendi. Orijinal tahmin JSON'u ve
ayrı performans projesi, kaynak ZIP'lerle byte düzeyinde aynı kaldı.
Canlı Telegram/LLM/football API çağrısı yapılmadı.

Sonraki adım: README'deki aktarım adımlarıyla kodu GitHub'a taşıma;
canlı archive JSON'larını koruma; ilk workflow ve operasyon botunu doğrulama.
Secrets yalnızca GitHub'da; yerel ortamda canlı erişimleri doğrulanamaz.
Ayrı performans botunun yeni puan sistemine geçirilmesi sonraki proje kapsamındadır.


## Sonradan onaylanan puanlama
Kicktipp 8/6/4/0 aktiftir; yukarıdaki eski 6/5/3/2/0 açıklaması önceki sürümün tarihsel kaydıdır.
