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
