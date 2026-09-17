# Champions League Performance Bot

UEFA Champions League 2026/27 tahmin arşivini bağımsız biçimde değerlendirir, haftalık ve sezon geneli performans görsellerini Telegram'a gönderir.

## Temel kurallar

- Puanlama: tam skor **6P**, kazanan + doğru gol farkı **5P**, farklı skorlu beraberlik **3P**, yalnız kazanan **2P**, yanlış sonuç **0P**.
- Başarılı her AI tahmini consensus oluşup oluşmamasından bağımsız puanlanır.
- API/model hatası veya üretilemeyen tahmin **0 puan değildir**; yalnızca coverage oranını düşürür.
- Consensus için en az **3 başarılı AI tahmini** gerekir. Ardından benzersiz strict-majority kuralı uygulanır.
- Consensus performansı bireysel AI performansından ayrı tutulur ve aynı 6/5/3/2/0 sistemiyle değerlendirilir.
- Tahmin kaydı olmayan bitmiş maç `UNAVAILABLE` olarak tutulur; AI başarısızlığına 0 puan yazılmaz.
- Ertelenen/iptal edilen terminal maçlar Matchday'i süresiz kilitlemez.
- FINAL rapor bir Matchday için yalnızca bir kez Telegram'a gönderilir.

## Rapor zamanı

GitHub Actions Salı-Perşembe 18:05-23:05 UTC arasında saatlik hafif kontrol yapar. Bot fixture verisindeki ilgili Matchday'in **son planlanan maç başlangıcından 60 dakika geçmeden** rapor oluşturmaz. Sonuçlar henüz tamamlanmamışsa FINAL rapor için sonraki kontrolde tekrar bakılır.

Bu performans botu tahmin AI'larını yeniden çağırmaz; prediction repo'daki arşivlenmiş tahminleri okur. Bu nedenle performans kontrolü Gemini/Qwen/Cohere/Mistral/GPT-OSS tahmin tokenı tüketmez.

## Telegram çıktısı

FINAL Matchday'de iki PNG gönderilir:

1. Haftalık AI performansı: toplam puan, ortalama /6, 6P/5P/3P/2P/0P dağılımı ve coverage; ayrıca consensus performansı.
2. Sezon geneli AI performansı: aynı metriklerin tüm FINAL Matchday'ler üzerinden toplamı.

## Mistral

Bu repo Mistral dahil modelleri çağırmaz; prediction repo'nun ürettiği `match_predictions.json` verisini değerlendirir. Mistral API/entegrasyon hatası burada 0 puan sayılmaz ve coverage ile görünür hale gelir. Mistral çağrısının düzeltilmesi veya alternatif modelle değiştirilmesi prediction repo tarafında yapılmalıdır.

## Secrets

- `FOOTBALL_DATA_API_KEY`
- `ANALYSIS_TELEGRAM_BOT_TOKEN`
- `ANALYSIS_TELEGRAM_CHAT_ID`
- `PREDICTION_REPO_TOKEN` — prediction repo private ise Contents: Read erişimi gerekir.

Varsayılan prediction repo: `yapayforzeka1/Haftalik-Mac-Tahmini`.

## Test

```bash
python -m unittest discover -s tests -v
```
