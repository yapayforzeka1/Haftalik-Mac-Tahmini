# v3 güncellemesi

## Davranış değişiklikleri
- Sabit puanlama 6/5/3/2/0; gol farkı kategorisi eklendi.
- İlk XI bulunamadığında 30 dakika eşiğinde araştırılmış tahmini kadro ile devam.
- Bir AI yanıtı bireyseldir; ortak kararda başarısız modeller paydaya girmez.
- Maç mesajları tek tek ve gerektiğinde bölünerek gönderilir; normal konsensüse görsel eklenir.
- Sonuç ve gönderim ayrı izlenir; görsel hatası yazılı tahmini/arşivi kaybettirmez.
- Hiçbir AI çalışmazsa ayrı istatistiksel tahmin veya veri eksikliği mesajı.
- Haftalık performans yayını bu botun ana akışından çıkarıldı.

## Öğrenme
- Maç öncesi girdiler, sürümler ve hash; maç sonrası faktör ve hata ölçümleri.
- Gelecek sonuçlar öğrenme bağlamına alınmaz.
- Onaylı sınırlı politika değişimi ve düşüş durumunda onaylı geri dönüş önerisi.
- Geçmiş arşivde bulunmayan kaynak/faktör bilgileri sonradan uydurulmaz.

## İşletim
- Üç OPERATIONS_TELEGRAM secret'ı kullanılır; yalnızca özel sohbet admin'i onaylayabilir.
- Düğme yanıtları zamanlanmış işte alınır, anlık değildir.
- State commit'i başarısız işten sonra da denenir; kurtarma artifact'i üretilir.
- Çevrimdışı testler: 55 başarılı. Canlı servis veya model erişim garantisi değildir.

## Aktarım
Paket canlı JSON arşivlerini içermez. Dosyaları mevcut repo köküne aynı yapıyla koyun.
.github/workflows/main.yml gizli klasör altında olduğundan atlamayın.
Mevcut match_predictions.json, weekly_reports.json ve weekly_schedule.json dosyalarını silmeyin.
Kodun eski sürümüne dönmek gerekirse v3'ün data/ ve maç arşivini ayrıca koruyun;
puanlamayı sessizce eski sürüme dönüştürmeyin.
