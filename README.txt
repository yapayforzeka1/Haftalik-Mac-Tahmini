Haftalik-Mac-Tahmini düzeltme paketi

İçerik:
- runner.py.patch: Bitmiş ve maç öncesi tahmini bulunmayan maçlar için geç Telegram uyarısını bastırır; operasyon arşivine bastırma nedenini yazar.
- tests/test_runtime.py.patch: Üç regresyon testi ekler:
  1. Bitmiş/tahminsiz maç sessizce arşivlenir.
  2. Canlı/tahminsiz maç için operasyon uyarısı korunur.
  3. Tahmini kayıtlı bitmiş maçta teslimat uyarısı korunur.

Önemli:
- Bu paket kaynak dosyaların tam kopyası değil, GitHub main dalındaki incelenen sürüme uygulanacak unified diff yamalarıdır.
- Yama T-60, kadro bekleme, AI çağrıları, sonuç güncelleme ve geçmiş tahmin kayıtlarına dokunmaz.
- Yama GitHub'a uygulanmadı; commit atılmadı ve Actions çalıştırılmadı.
- Uygulamadan sonra offline testler çalıştırılmalıdır: pytest -q
