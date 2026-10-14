# Haftalık Maç Tahmini — v3

Maç öncesi tahmin, 90 dakika sonuç değerlendirmesi ve kullanıcı onaylı öğrenme sistemi.
**Performans Takip Botu ile Kicktipp 8/6/4/0 standardı ortaktır.**

## Sabit kurallar

| Başarı | Puan |
|---|---:|
| Tam skor | 8 |
| Doğru 1-X-2 ve doğru gol farkı, farklı skor | 6 |
| Doğru beraberlik, farklı skor | 6 |
| Doğru 1-X-2, yanlış gol farkı | 4 |
| Yanlış sonuç | 0 |

Her model ve turnuva aşamasında aynıdır. 90 dakika + hakem ek süresi değerlendirilir.
15+15 dakika ve seri penaltılar hariçtir. Sağlayıcı uzatmalı bir maç için 90 dakika
skorunu vermiyorsa değerlendirme bekler; fullTime yanlışlıkla kullanılmaz.
Her tahmin tek kategoriden puan alır. Yanıt vermeyen model hata/erişilebilirlik
olarak kaydedilir; başarısız tahmin sayılmaz.

Yeni tahminlerde konsensüs için en az üç geçerli model ve başarılı modellerin salt çoğunluğu gerekir.
Sonuç ve skor çoğunluğu ayrı hesaplanır. Örneğin 3/4, %75 **uzlaşmadır**, maçın
kazanılma olasılığı değildir. AI güveni öznel güven ortalamasıdır.
Ortak skor aynı tabloyla; yalnızca ortak sonuç belli ise (ortak skor yoksa)
doğru 1-X-2 için 4, yanlış 1-X-2 için 0 puan verilir. Konsensüs yoksa ortak puan yoktur; bireysel puanlar vardır.

## Çalışma

1. Operasyon botunun bekleyen kararlarını oku; yetkili kullanıcıyı doğrula.
2. Arşivlenmiş gönderimleri yeniden üretmeden sürdür; biten maçları puanla.
3. Öğrenme özetlerini güncelle; yeterli veri varsa onaya sunulacak öneri hazırla.
4. Maçtan 60 dakika önce kontrol penceresine gir. Resmi XI erken/40/30 dakika
   pencerelerinde kontrol edilir. XI varsa tahmin hazırlanır. Yoksa 30 dakika kala
   kaynaklı kadro araştırması yapılır. Actions gecikirse maç başlamadan yakalama yapılır.
5. football-data.org, API-Football ve teyitli FotMob kadroları denenir. Resmi kadro
   bulunamazsa araştırma; sakatlık, ceza ve transfer uygunluğunu kontrol eden tahmini
   XI üretmeye çalışır. Eksik isimler uydurulmaz. Tam XI bulunmasa da maç atlanmaz.
6. Aynı araştırma tüm modellere verilir; kadro/araştırma/historical veriler ve sürümler
   tahminden önce dondurulur. Bağımsız sağlayıcılar eşzamanlı, aynı Groq hesabındaki
   iki model sırayla çağrılır. Süre ve çıktı limitleri vardır.
7. Üç veya daha fazla geçerli yanıt varsa salt çoğunluk değerlendirilir. Bir veya iki
   yanıt bireysel gösterilir. Tümü başarısızsa sınırlı yeniden denemeden sonra sade
   tahmin üretilemedi tablosu gönderilir; istatistiksel veya bahis yedeği yayımlanmaz.
8. Her maç için onaylanan tablo tek görsel olarak gönderilir. Aynı metin ayrıca
   gönderilmez. Görsel gönderim kaydı tutularak tamamlanan gönderimler tekrarlanmaz.

## Öğrenme ve onay sınırları

Bu sürüm LLM ağırlıklarını yeniden eğitmez ve isabet artışı garantisi vermez.
Her maç için puan, tam skor, sonuç doğruluğu, gol sapması, kullanılan veri türleri,
maç öncesi gerekçeler, kaynaklar ve resmi XI durumu saklanır. Modelin kullandığını
bildirdiği faktörler ile arşivde mevcut veriler ayrı ölçülür. Birlikte görülme nedensellik
değildir. Eski arşivlerde faktör etiketi yoksa sonradan uydurulmaz.

Sonraki maçlara yalnızca o andan önce sonuçlanmış ve maç öncesi oluşturulduğu
zaman damgasıyla doğrulanabilen kayıtlar özetlenerek verilir. Geçmiş maçlara bugün
web araştırması yapılıp "maç öncesi" test sonucu diye sunulmaz. Öğrenme özetleri
ücretsiz deterministik hesaplanır; maç sonu ek LLM çağrısı yapılmaz.

İlk sürümün ayar alanı sınırlıdır: dengeli analiz ve resmi XI yokken kadro belirsizliğini
öne çıkaran analiz politikası. XI var/yok gruplarında en az sekizer uygun maç ve
15 yüzde puanlık tam skor farkı oluşursa gözlemsel kanıtla bir **deney önerisi** çıkar.
Bu, yeni politikanın önceden başarı kanıtladığı anlamına gelmez. Yeni politika sadece
onaydan sonraki, henüz girdileri dondurulmamış tahminlere uygulanır. Aynı koşuldaki
eski/yeni politika örneklerinde en az sekizer maç ve belirgin düşüş varsa eski
politikaya dönüş de onaya sunulur. Serbest kod düzenleme veya onaysız ağırlık değişimi yoktur.

## Şampiyonlar Ligi AI Operasyon

- ✅ Onayla: gösterilen sürüm ve talimatı uygula.
- ❌ Reddet: mevcut politikayı koru.
- 📋 Ayrıntı: kanıt, maç kimlikleri, yeni talimat ve sınırlamaları göster.

Yalnızca tanımlı kullanıcının tanımlı özel sohbetteki, doğru öneri mesajına ait
kararı kabul edilir. Tekrarlı tıklamalar tekrar uygulamaz. Öneri 7 gün sonra veya
ayar sürümü değişince geçersizdir. Sessizlik onay değildir. İlk başarılı bağlantıda
hazır mesajı, sonuçlar değiştikçe öğrenme özeti iletilir.

Düğmeler GitHub Actions çalıştığında işlenir; anlık yanıt beklenmemelidir. Telegram
bekleyen güncellemeleri en fazla 24 saat tutar. Uzun kesintiden sonra karar işlenmediyse
yeniden tıklayın. Başka bir süreç aynı botun getUpdates kuyruğunu tüketmemeli ve
webhook kurulu olmamalıdır. Gecikmiş callback onayı zaman aşımına uğrasa bile karar
normal mesajla bildirilir. Sayısal admin ID/token loglara veya arşive yazılmaz.

## Secrets ve değişkenler

GitHub Settings → Secrets and variables → Actions:

| Secret | Anlam |
|---|---|
| TELEGRAM_BOT_TOKEN | Mevcut tahmin botunun token'ı |
| TELEGRAM_CHAT_ID | Maç mesajlarının hedefi |
| FOOTBALL_DATA_API_KEY | Fikstür ve sonuç API anahtarı |
| API_FOOTBALL_KEY | İsteğe bağlı ikinci kadro sağlayıcısı |
| GEMINI_API_KEY | Araştırma ve Gemini tahmini |
| MISTRAL_API_KEY | Mistral tahmini |
| GROQ_API_KEY | İki Groq modeli |
| COHERE_API_KEY | Cohere tahmini |
| OPERATIONS_TELEGRAM_BOT_TOKEN | Yeni operasyon botu token'ı |
| OPERATIONS_TELEGRAM_CHAT_ID | Senin özel sohbet ID'n |
| OPERATIONS_TELEGRAM_ADMIN_USER_ID | Yetkili Telegram kullanıcı ID'n |

Özel sohbette son iki ID aynıdır. Yeni bota /start gönderilmiş olmalıdır.
API anahtarları eksikse ilgili model başarısız çağrı sayılır. Model API kimlikleri
GEMINI_MODEL, MISTRAL_MODEL, GROQ_QWEN_MODEL, GROQ_120B_MODEL, COHERE_MODEL repository
variables ile değiştirilebilir; varsayılanlar kaynak projeden korunmuştur. Canlı
hesabın model erişimi/kotası çevrimdışı testlerle doğrulanamaz.

## Arşivler ve kurtarma

- match_predictions.json: asıl tahmin, girdiler, sonuç ve gönderim makbuzları.
- data/pre_v3_predictions.json: ilk v3 çalışmasında eski arşivin değişmez yedeği.
- legacy_evaluation: her eski kaydın önceki puanlaması korunur.
- post_match_analysis: yeni ölçümler ve veri kullanımı incelemesi.
- data/operations.json: politika, öneri, karar, Telegram cursor, öğrenme özeti.
- data/provider_cache.json: süreli sağlayıcı önbelleği.

JSON bozuksa işlem durur; boş veriyle üzerine yazılmaz. Dosya güncellemeleri atomiktir.
Workflow hata olsa da tamamlanan adımları commit etmeyi dener; commit/push hatasında
kurtarma artifact'i bırakır. Workflow concurrency aynı botun eşzamanlı çalışmasını önler.
Telegram ve GitHub arasında ortak işlem olmadığı için mesajın gidip makbuzun diske veya
GitHub'a ulaşmadığı dar kesinti aralığında tekrar mesaj mümkündür; tam exactly-once
iddiası yoktur. GitHub tamamen iptal edilirse son commit sonrası ilerleme kaybolabilir.

GitHub cron kesin zaman garantisi vermez; ücretsiz hizmet kesintileri ve veri yokluğu
nedeniyle her maça zamanında skor üretme garantisi yoktur. Önceden görülen bir maçın
penceresi kaçarsa uyarı gönderilir; maç başladıktan sonra yeni tahmin yayımlanmaz.

Eski weekly_reports.json / weekly_schedule.json ve haftalık görsel araçları arşiv
uyumluluğu için durur, ana akış bunları çağırmaz. Ayrı performans botu da aynı Kicktipp 8/6/4/0 puanlarını kullanır.

## Yerel test ve devreye alma

Python 3.12:

```shell
python -m pip install -r requirements.txt
python -m pytest -q
```

Testler canlı Telegram/AI servisine bağlanmaz. TEST_MODE=true ayrı test_runtime dizini
kullanır, operasyon önerilerini işlemez; ancak manuel workflow testi gerçek Telegram'a
TEST etiketiyle mesaj gönderir ve API kotası tüketebilir.

Güncelleme ZIP'inde canlı arşiv JSON'ları yoktur. Kod dosyalarını aynı isimlerin üzerine
kopyalayın; repodaki match_predictions.json ve diğer mevcut JSON'ları koruyun.
README, requirements.txt, pytest.ini, tests/ ve gizli .github/workflows/main.yml dahil
olmalıdır. Önce testlerin geçtiğini kontrol edin. İlk canlı denemede secret erişimi,
operasyon hazır mesajı ve workflow arşiv commit'ini kontrol edin. Bu teslimatta canlı
servis bağlantısı veya deployment yapılmamıştır.

Teknik kaynaklar: [90 dakika skor alanı](https://docs.football-data.org/general/v4/overtime.html),
[kadro şeması](https://docs.football-data.org/general/v4/match.html),
[Telegram updates](https://core.telegram.org/bots/api#getupdates),
[GitHub zamanlama](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Onaylı Telegram tabloları — format 4

- Kazanan ve skor ortak: yalnızca özet; ortak skoru seçen kısa model adları dahil.
- Kazanan ortak, skor farklı: özet ve AI Modelleri | Skor | Oy tablosu.
- Ortak karar yok: özet ve AI | Kazanan ve kısa sebep | Skor | Oy tablosu.
- 1–2 yanıt: özet/yanıt sayısı ve AI | Kazanan ve kısa sebep | Skor tablosu.
- 0 yanıt: Maç | Saat | AI yanıtı | Durum; Tahmin üretilemedi.

Oy, aynı skoru seçen başarılı modellerin sayısı / başarılı model sayısıdır.
Yanıt sayısında beş modelin tamamı paydada yer alır. Skorlar ev sahibi–deplasman
sırasındadır. Kısa gerekçe modelden alınır; ayrıntılı gerekçeler ve model kimlikleri
arşivde korunur. Görünüm tahmin anında dondurulur. Eski tahminler yeniden gönderilmez;
eski kayıtların iki modelli ortak karar eşiği korunur. Yeni kayıtlar üç model eşiği taşır.
Maç sonucu mesaj tasarımı bu güncellemenin kapsamında değildir.

## AI servis hata düzeltmesi

- Groq Qwen varsayılanı `qwen/qwen3.8-27b` oldu. GitHub Variables içinde eski
  `qwen/qwen3.6-27b` kalsa bile bu belirli değer yeni kimliğe çevrilir. Diğer açık
  model tercihleri korunur. Yeni Qwen sonuçları yeni model adıyla kaydedilir;
  bireysel sonuçlarda gerçek API model kimliği de tutulur. Eski arşivler değiştirilmez.
- Cohere sade JSON nesnesi moduyla çağrılır; isteğe bağlı JSON şeması gönderilmez. Thinking parametresi gönderilmez; modelin varsayılanı kullanılır
  ve yanıt bütçesi 2048 token olur. Eksik/kesilmiş çıktı kabul edilmez;
  `EMPTY_RESPONSE`, `RESPONSE_TRUNCATED` ve `INVALID_JSON` ayrı raporlanır.
- Her sağlayıcı için tek bir yeniden deneme katmanı vardır: geçici 429/5xx/timeout
  hatalarında toplam en fazla üç deneme. Bir model başarılıyken diğerlerinin geçici
  hataları da yeniden denenir. Geçersiz/eksik JSON için en fazla bir ek deneme vardır.
- Bekleme artarak ilerler; varsa HTTP `Retry-After` değerinden önce istek atılmaz.
  Bir bekleme 60 saniyeyi aşacaksa veya maç öncesi süre yetersizse yeniden deneme
  yapılmaz. Hesap kotası, model erişim izni veya sağlayıcı kesintisi kodla garanti
  edilemez. Hata mesajları sırları içerebileceğinden ham yanıtlar loga yazılmaz.

Güncellemeyi yüklerken `.github/workflows/main.yml` dosyasını da değiştirin.
Ardından Actions üzerinden `test_mode=true` ile çalıştırıp `AI SONUC OZETI` ve
`AI TOPLAM` satırlarını kontrol edin. Bu paket, format ve tanılama güncellemelerinin
üzerine uygulanır. Yerel testlerde canlı servislere veya Telegram'a bağlanılmaz.

Doğrulanan teknik kaynaklar:
[Groq Qwen modeli](https://console.groq.com/docs/model/qwen/qwen3.8-27b),
[Cohere JSON biçimi](https://docs.cohere.com/v2/reference/chat),
[Cohere düşünme ayarı](https://docs.cohere.com/docs/reasoning),
[Mistral hata yönetimi](https://docs.mistral.ai/resources/error-glossary),
[Gemini yeniden deneme](https://ai.google.dev/gemini-api/docs/troubleshooting).


### Sağlayıcı hata düzeltmesi — ikinci paket

- Cohere 422 hatası için istek sadeleştirildi: `response_format={"type":"json_object"}`.
  Gelen tahminin skor/sonuç tutarlılığı yine uygulamada doğrulanır.
  Önceki log hata gövdesini içermediğinden 422'nin kesin sebebi henüz doğrulanmış değildir.
- Mistral 429 sonrasında en az 60 saniye beklenir. Sağlayıcının daha uzun
  Retry-After süresi kısaltılmaz; maç öncesi süre yetmezse yeniden çağrı yapılmaz.
- Sağlayıcı açıkça yetersiz kota/bakiye bildirirse tekrar denenmez.
- `AI DETAY` satırları token hızı, istek hızı, kota veya kontrol edilmesi gereken
  istek alanını sabit kodlarla gösterir. Ham hata gövdesi ve API anahtarları yazılmaz.
  `CHECK_...` kesin kök neden değil, sağlayıcı yanıtında adı geçen alandır.
- Gemini 503/504 için mevcut sınırlı yeniden deneme sürer; servis erişilebilirliği
  veya hesap kotası bu paketle garanti edilemez.
- Telegram formatları ve ortak karar kuralları korunur; yüzde 58 gönderim eşiği yoktur.

Kurulum: ZIP içindeki dosyaları mevcut deponun aynı yollarına kopyalayın.
Önceki güncellemelerin uygulanmış olması gerekir. GitHub Actions üzerinden TEST
modunda bir kez çalıştırın; kalan sorun varsa `AI DETAY` ve `AI SONUC OZETI`
satırlarını paylaşın. TEST modu gerçek API kullanır; yerel pytest testleri kullanmaz.


### Cohere canlı karşılaştırması sonrası düzeltme

Kullanıcının canlı testinde JSON modu açık ve thinking parametresi olmadan
HTTP 200 / VALID_PREDICTION alındı. Thinking disabled ile yapılan diğer test
HTTP 422 verdi. Ana bot ilk testte çalışan ayara geçirildi: JSON nesnesi modu
korunur, thinking parametresi tamamen çıkarılır. Bu sonuç bütün maçlarda veya
gelecekteki servis koşullarında başarı garantisi değildir.
Skor/sonuç doğrulaması, 2048 token bütçesi ve kesilmiş yanıt kontrolü korunur.
Mistral 429 ve Gemini servis hataları bu değişiklikle çözülmüş sayılmaz.

## Puan sürümü 4 geçişi

1. ve 2. hafta dahil geçmiş 90 dakika sonuçları `regrade_archived_results` ile yeniden puanlanır. Hemen önceki puanlar `pre_kicktipp_evaluation` içinde; varsa daha eski `legacy_evaluation` ayrıca korunur, tahminler ve Telegram gönderim makbuzları değiştirilmez. Eksik veya teyitsiz maçlar puanlanmaz.
