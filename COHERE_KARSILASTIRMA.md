# Cohere ayar karşılaştırması

Önceki AI teşhis paketi yüklü olmalıdır; diagnose_providers.py içindeki maskeleme
fonksiyonları kullanılır. Bu dosyaları aynı yollarla varsayılan GitHub dalına ekleyin.
Actions → Cohere Ayar Karşılaştırması → Run workflow.
Cohere ayarlarını karşılaştır adımındaki COMPARE satırlarını paylaşın.

Aynı sentetik tahmin metni ve token bütçesiyle en fazla iki gerçek istek yapılır:
1. JSON modu açık, thinking parametresi gönderilmez (model varsayılanı geçerlidir).
2. response_format gönderilmez, thinking disabled gönderilir.

Yanıtın tamamlanması, JSON ayrıştırması, kazanan/skor tutarlılığı, güven puanı
aralığı ve sebep alanları kontrol edilir. VALID_PREDICTION yalnızca biçim ve
bu tutarlılık kontrollerinin geçtiğini belirtir; gerçek maç doğruluğu değildir.
Thinking varsayılanı token bütçesini tüketirse RESPONSE_TRUNCATED görülebilir;
bu sonuç tek başına istek ayarının desteklenmediğini kanıtlamaz.

Otomatik yeniden deneme yapılmaz. Yetkilendirme veya hız sınırı hatasında ikinci
çağrı atlanır. Küçük API kullanımı oluşur. Telegram, arşiv ve ana bot ayarları
etkilenmez. Diğer AI modelleri çağrılmaz. Canlı kontrolü yalnızca bir kez başlatın.
Bağımlılık kurulumu hariç her istek için 45 saniyelik ağ zaman aşımı uygulanır.
Yerel testler canlı API çağırmadan geçmiştir (127 test).
