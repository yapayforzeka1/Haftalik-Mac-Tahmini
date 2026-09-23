# Tahmin projesi ayrıştırma yaması

Kaynak: 23 Eylül 2026 tarihinde yüklenen Haftalik-Mac-Tahmini-main.zip.
ZIP içindeki dosyaları mevcut projede aynı yollara yükleyin. Hiçbir JSON arşivini silmeyin.
Yeni bot kullanılacaksa TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID Secrets güncellenir.

Telegram çıkışı yalnızca maç öncesi tahminlerdir. Sonuç değerlendirme ve kaçırılan
maç operasyon uyarıları gönderilmez. actual, puan, post_match_analysis ve düzeltme
geçmişi arka planda kaydedilir. result_sent artık sonuç kaydetme koşulu değildir;
eski alanlar uyumluluk için korunur ve gönderilmiş gibi işaretlenmez.

runner.py artık Operations polling/öneri/performans bildirimi çalıştırmaz.
operations.py gibi eski modüller yerinde kalır, bot girişinden çağrılmaz.
learning_context ve audit korunur. data/operations.json içindeki eski kararlar
silinmez; bağımsız Operations başlangıçta kopyasını alır.

Görseller, logolar, match_report.py, render_preview.py, AI istemleri, konsensüs,
puanlama, veri sağlayıcıları ve araştırma değiştirilmedi. Normal mod son 60 dakikada
aday seçer; ilk 11 yoksa 30 dakikaya kadar bekler. 15–75 dakika kuralı mevcut değildi.
TEST_MODE üretim kayıtları yerine test_runtime kullanır. visual_test AI çağırmaz;
çalıştırılırsa örnek tahmin görselini Telegram'a gönderir ve logo indirmesi yapabilir.

Secrets (mevcut): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, FOOTBALL_DATA_API_KEY,
API_FOOTBALL_KEY, GEMINI_API_KEY, MISTRAL_API_KEY, GROQ_API_KEY, COHERE_API_KEY.
Ops Telegram secrets artık bu projenin workflow'unda kullanılmaz.
Yeni isteğe bağlı entegrasyon: OPERATIONS_REPO variable, OPERATIONS_BRANCH variable,
OPERATIONS_REPO_TOKEN secret (sadece Operations deposunda Contents: Read).
Önce Operations initialize_only çalıştırılmalı; approved_policy.json yoksa bağlamayın.
Bağlandıktan sonra dosya eksik/bozuk/eski revizyonsa işlem durur; keyfi talimat kabul edilmez.
Bağlanmazsa mevcut kaydedilmiş politika aynen devam eder.

Telegram Bağlantı Kontrolü manuel getMe/getChat testi sağlar, mesaj/AI çağrısı yapmaz.
