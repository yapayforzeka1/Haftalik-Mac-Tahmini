# Haftalık Maç Tahmini — V2

Amaç: Proje 2'nin mevcut V1 akışını bozmadan, doğru skor tahminini güçlendirmek.

## V2 değişiklikleri
- Son 5 form verisine ev/deplasman ayrımı eklendi.
- Maç öncesi dinlenme süresi ve son 14/21 gündeki maç yükü hesaplanıyor.
- Güncel araştırma katmanı; ligler arası kalite farkı, rakip kalitesi, fikstür yoğunluğu, motivasyon, rotasyon ve resmi kadro/ilk 11 durumunu açıkça araştırıyor.
- 5 AI aynı ortak araştırma paketini kullanıyor.
- AI prompt'u exact-score odaklı hale getirildi; önce gol seviyesini değerlendirmesi, sonra tek skor seçmesi isteniyor.
- Skor ile HOME/DRAW/AWAY yönünün tutarlı olması zorunlu hale getirildi.
- Her AI en fazla 3 skor adayı döndürebiliyor; nihai sistem skoru yine tek skor olarak kullanıyor.
- Arkadaşlar arasındaki puanlama, tahmin üretimini ağırlıklandırmıyor.
- Bot 2 haftalık/genel rapor ayrımı korunuyor.
- 429 araştırma hatasında fallback davranışı korunuyor.

## Bilinçli sınırlar
- Lig gücü ve rakip gücü için uydurma sabit puanlar kullanılmadı; güncel araştırma bunları kaynaklarla bağlamlandırıyor.
- xG/xGA ve şut verisi güvenilir kaynakta bulunursa araştırma paketine alınır; bulunamazsa uydurulmaz.
- Resmi ilk 11 açıklanmadan tahmin ikinci kez çalıştırılmıyor; V2'nin bu adımı için ayrı bir tetikleme mimarisi gerekir.

## Doğrulama
`python -m py_compile *.py && python test_core.py`
sonucu: `CORE TESTS OK`
