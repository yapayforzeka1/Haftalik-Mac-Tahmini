# Proje 2 — V2.1 araştırma düzeltmesi

## Gemini araştırma katmanı
- Araştırma modeli `gemini-2.5-flash` olarak değiştirildi.
- Google Search grounding korunuyor.
- Gemini 3.x ücretsiz API katmanında Search grounding kullanılamadığı için V2 testinde alınan `429 RESOURCE_EXHAUSTED` sorununun ana kaynağı bu uyumsuzluktu.
- Araştırma çağrısına 429/503 için sınırlı exponential backoff eklendi.
- 3 denemeden sonra araştırma yine başarısızsa sistem çökmüyor; mevcut fallback davranışı devam ediyor.

## Test
`python -m py_compile *.py` ve `python test_core.py` başarılı: `CORE TESTS OK`.

## Not
Gemini API anahtarının kendi 2.5 Search grounding kotası ayrıca doluysa yine 429 alınabilir. Google AI Studio'daki Rate Limits/Usage bölümünden kontrol edilmelidir.


## V2.2 zamanlama / resmi XI
- Normal tahmin penceresi maçtan 15–75 dakika öncesidir.
- Tahmin, resmi ilk 11 doğrulanmadan normal modda finalize edilmez.
- football-data.org maç detayındaki lineup verisi önce kontrol edilir; araştırma katmanı resmi kaynaklarla çapraz kontrol eder.
- Böylece resmi XI açıklandıktan sonra AI'lar final tahmini üretir ve hedef, maçtan en geç 15 dakika önce Telegram'a göndermektir.
- GitHub Actions schedule 5 dakikada bir kontrol eder.
- TEST_MODE, geliştirme/test amacıyla resmi XI kapısını bypass edebilir; test tahminleri gerçek arşive yazılmaz.
