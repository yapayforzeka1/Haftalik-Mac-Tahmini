# Haftalık Maç Tahmini

UEFA Şampiyonlar Ligi 2026/27 için maç öncesi çoklu yapay zekâ analiz, tahmin ve haftalık performans botu.

## Akış
1. football-data.org: fikstür ve son maçlar. Champions League puan durumu endpoint'i 404 verirse analiz durmaz; standings opsiyonel kabul edilir.
2. Gemini Google Search grounding: güncel haber, sakatlık/ceza, xG/xGA, şut, kadro ve taktik araştırması.
3. Araştırma başarısız olsa bile sistem yapılandırılmış verilerle AI havuzuna devam eder.
4. 5 AI bağımsız olarak tahmin üretir.
5. Başarılı AI sayısı kaç olursa olsun sonuçlar değerlendirilir. Konsensüs yalnızca benzersiz **salt çoğunluk** varsa oluşur; çoğunluk yoksa sistem ortak sonuç uydurmaz. Aynı kickoff dakikasındaki maçlar tek Telegram yazılı paketi halinde gönderilir; normal konsensüs maçları görsel kart olarak da gönderilir.
6. Tahmin penceresi normalde maçtan **35-75 dakika** öncesidir.
7. `match_predictions.json` haftalar boyunca maç, 5 AI oyu, konsensüs ve gerçek sonuçları saklar; sonuçlar sonradan yeni konsensüs kurallarıyla yeniden değerlendirilebilir.
8. Maç tamamlandığında puanlama otomatik yapılır.
9. Bir Matchday'in planlanan son maç başlangıcından 1 saat sonra haftalık rapor hazırlanır. Ertelenen/iptal edilen maçlar raporu bloke etmez.
10. Haftalık rapor Telegram'a görsel olarak gönderilir. Ardından haftaları birbirinden ayrı tutan genel sezon performans görseli gönderilir.
11. `weekly_reports.json` her haftanın bağımsız snapshot'ını sabit tutar; `weekly_schedule.json` ilk görülen Matchday program kesitini saklayarak erteleme/reschedule durumunda rapor saatinin kaymasını önler.

## Kilitli puanlama sistemi
- **5 puan:** Tam skor doğru.
- **3 puan:** Kazanan doğru, skor yanlış.
- **5 puan:** Tahmin beraberlik ve gerçek maç da beraberlik; skor farklı olsa bile.
- **0 puan:** Sonuç yanlış.

`2 puan` ayrı bir puan kategorisi değildir. 5 yerine 3 alınması, tam skor ile sadece sonucu bilmek arasındaki 2 puanlık farktır.

## Konsensüs ve anlaşmazlık kuralı

- **Kazanan konsensüsü:** Başarılı AI'ların benzersiz salt çoğunluğu gerekir. Örneğin 4 AI'dan 2-2 dağılım varsa ortak karar yoktur.
- **Skor konsensüsü:** Tam skor için de ayrıca benzersiz salt çoğunluk gerekir.
- Kazanan ortak, skor ortak değilse **SONUÇ ORTAK — SKOR AYRIŞTI** formatı kullanılır; skor tek bir AI'ın tahmini olarak konsensüs diye gösterilmez.
- Kazanan konusunda da ortaklık yoksa **ORTAK KARAR YOK** formatı kullanılır; her başarılı AI'ın sonucu ve skoru ayrı gösterilir.
- Ortak karar olmayan maçlar konsensüs puanına dahil edilmez. Buna karşılık tüm başarılı AI'ların bireysel tahminleri normal şekilde puanlanır.
- Eski arşivlerdeki çoğunluk/puan bilgileri, maç sonucu geldiğinde bireysel AI oylarından yeniden hesaplanır; böylece eski hatalı plurality konsensüsleri düzeltilir.

## Haftalık performans kuralı
- Her Matchday kendi içinde değerlendirilir.
- Haftalık rapor yalnızca o haftanın maçlarını ve sonuçlarını içerir.
- Bir haftanın raporu oluşturulduktan sonra o haftanın snapshot'ı değişmez.
- Sonraki hafta önceki haftaya eklenmez.
- Ayrı **Genel Performans** görseli 1. haftadan itibaren haftaları karşılaştırır ve sezon toplamını kümülatif gösterir.

## Telegram maç tahmin formatı
Maç başlamadan önce Telegram'a iki parça gönderilir:
1. Yazılı tahmin mesajı.
2. Aynı içeriğin görsel maç kartı.

Tek maç örneği:
```text
🏆 ŞAMPİYONLAR LİGİ 2026/27
⚽ MAÇ TAHMİNİ

📅 16.09.2026   ⏰ 19:45

⚽ Juventus — Dortmund
🤖 Kazanan: Juventus — %80 (4/5)
🎯 Skor: 2-1 — %60 (3/5)
📊 AI Güveni: %80

ℹ️ Bu oranlar maç öncesi AI konsensüsünü gösterir.
Puanlama maç sonucu belli olduktan sonra yapılacaktır.
```

Aynı kickoff dakikasında 4 maç varsa bunlar 4 ayrı mesaj yerine tek yazılı paket ve tek 4 kartlı görsel olarak gönderilir.

Buradaki yüzdeler gerçek kazanma olasılığı değildir; başarılı AI'ların konsensüs oranıdır. Maç başlamadan puan gösterilmez. Puanlama yalnızca gerçek sonuç geldikten sonra yapılır.

## Haftalık görsel rapor
Haftalık raporda:
- Maçlar kronolojik sırada gösterilir.
- Her maçın gerçek skoru bulunur.
- 5 AI'ın her bir tahmini ve aldığı puan gösterilir.
- Konsensüs tahmini ve puanı gösterilir.
- Alt bölümde haftalık AI performansı ve konsensüs performansı yer alır.

Genel performans görselinde haftalar ayrı sütunlarda, sezon toplamı ve ortalama puanla birlikte karşılaştırılır.

## AI havuzu
- Gemini 3.6 Flash
- Mistral Small Latest
- Groq Qwen 3.6 27B
- Cohere Command A+
- Groq GPT-OSS 120B

## GitHub Secrets
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `FOOTBALL_DATA_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`, `COHERE_API_KEY`

API anahtarları kod içine yazılmamalıdır.

## Test modu
GitHub Actions → **Run workflow** üzerinden `test_mode=true` seçilirse 35-75 dakika filtresi bypass edilir ve en yakın gelecek Champions League maçıyla Telegram testi yapılır. Test modu tahmini `match_predictions.json` içine kaydetmez.
