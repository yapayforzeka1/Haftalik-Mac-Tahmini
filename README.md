# Haftalık Maç Tahmini

UEFA Şampiyonlar Ligi 2026/27 için maç öncesi çoklu yapay zekâ analiz ve tahmin botu.

## Akış
1. football-data.org: fikstür, puan durumu ve son maçlar.
2. Gemini Google Search grounding: güncel haber, sakatlık/ceza, xG/xGA, şut, kadro ve taktik araştırması.
3. Araştırma başarısız olsa bile sistem yapılandırılmış verilerle AI havuzuna devam eder.
4. 5 AI bağımsız olarak tahmin üretir.
5. En az 3/5 başarılı AI varsa konsensüs oluşturulur ve Telegram'a gönderilir.
6. `match_predictions.json` haftalar boyunca tahmin, AI oyları, araştırma, gerçek sonuç ve performansı saklar.
7. Bitmiş maçlar sonraki çalıştırmada otomatik sonuçlandırılır; ilk sonuçlandırmada Telegram'a sonuç mesajı gönderilir.
8. Takım geçmişi ve AI performansı sonraki analizlere bağlam olarak verilir.

## AI havuzu
- Gemini 3.6 Flash
- Mistral Small Latest
- Groq Qwen 3.6 27B
- Cohere Command A+
- Groq GPT-OSS 120B

## GitHub Secrets
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `FOOTBALL_DATA_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`, `COHERE_API_KEY`

API anahtarları kod içine yazılmamalıdır.
