# AI sağlayıcı teşhisi

Bu paket mevcut güncellenmiş Şampiyonlar Ligi deposuna eklenir.
Normal bot, Telegram formatları ve arşivler değiştirilmez.

1. ZIP içindeki dosyaları aynı dizin yapısıyla GitHub deposuna yükleyin.
   `.github/workflows/provider-diagnostics.yml` yolunun başındaki nokta önemlidir.
2. Workflow dosyasını deponun varsayılan dalına ekleyin.
3. Actions → AI Sağlayıcı Teşhisi → Run workflow seçin.
4. Sağlayıcıları kontrol et adımındaki `DIAG |` satırlarını paylaşın.

Mevcut GEMINI_API_KEY, MISTRAL_API_KEY ve COHERE_API_KEY secrets kullanılır.
Model değişkenleri normal bot ile aynıdır. Ek anahtar gerekmez.
En fazla dört gerçek API isteği yapılır: Gemini 1, Mistral 1, Cohere 1–2.
Tekrar deneme yoktur. Küçük miktarda token tüketebilir. Telegram mesajı göndermez.
Bağımlılık kurulumu hariç genellikle birkaç dakika içinde biter.

Cohere basit isteği reddederse ikinci istek atlanır. Kabul ederse botun güncel
JSON/thinking ayarlarıyla sentetik bir maç bağlamı gönderilir; gerçek tahmin sayılmaz.
OK yalnızca HTTP kabulünü belirtir; tahmin kalitesini veya JSON içeriğini doğrulamaz.
Provider hatası olsa da teşhis akışı tamamlanabilir; yeşil Actions işareti yerine
DIAG satırlarındaki her sağlayıcının sonucunu inceleyin.

Hata yanıtlarının yalnızca seçili açıklama alanları yazılır. Ortamda tanımlı
anahtarlar, tokenlar, URL'ler ve authorization değerleri maskelenir.
Ham istekler, yanıt başlıkları ve başarılı model yanıtları yazılmaz.
Yerel testler canlı API çağırmadan sahte yanıtlarla yürütülmüştür: 117 test geçti.
