from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

RESEARCH_MODEL = "gemini-2.5-flash"


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("Araştırma JSON olarak ayrıştırılamadı.")
        return json.loads(match.group(0))


def _compact(value: Any, max_chars: int) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:max_chars]


def empty_research(reason: str) -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "summary": "Güncel web araştırması alınamadı; AI'lar yapılandırılmış futbol verisiyle devam etti.",
        "home": {}, "away": {}, "comparison": "",
        "league_context": {}, "opponent_quality": {}, "fixture_congestion": {},
        "motivation": {}, "rotation_risk": {}, "official_squad": {},
        "official_xi": {}, "news": [], "conflicts": [reason], "sources": [],
        "research_confidence": "LOW",
        "researched_at": datetime.now(timezone.utc).isoformat(),
    }


def research_match(client: Any, home_team: str, away_team: str, match_context: dict[str, Any]) -> dict[str, Any]:
    from google.genai import types
    prompt = f"""
UEFA Champions League 2026/27 maç öncesi, doğru SKOR tahminini desteklemek için güncel ve eleştirel araştırma yap.
Maç: {home_team} - {away_team}
Araştırma tarihi: {datetime.now(timezone.utc).date().isoformat()}

Yapılandırılmış veriler:
{_compact(match_context, 14000)}

Google Search ile mümkün olduğunca bağımsız kaynakları çapraz kontrol et.
Öncelik: UEFA ve kulüplerin resmi kaynakları, güvenilir spor basını ve güvenilir istatistik kaynakları.
Son 60 gün ve özellikle son 5 resmi maça odaklan. Bulamadığın veriyi uydurma; null veya "bulunamadı" kullan.

ZORUNLU ARAŞTIRMA KONTROL LİSTESİ:
1) Son 5 maç sonuçları, atılan/yenilen goller ve form trendi.
2) Son 5 rakibin seviyesi; mümkünse rakibin kendi ligindeki konumu ve Avrupa seviyesi.
3) Takımın kendi lig seviyesi ve Avrupa/UEFA seviyesi; ligler arasındaki kalite farkını dikkate al.
4) İç saha/deplasman performansı.
5) xG/xGA, şut ve isabetli şut; güvenilir kaynak varsa son dönem ortalamalarını ver.
6) Sakatlıklar, cezalar, son maç kadrosu/rotasyonu ve oyuncu formu.
7) Muhtemel XI, önemli oyuncular ve teknik direktör/taktik yaklaşımı.
8) Taktik eşleşme ve rakibin oyun tarzının bu maça etkisi.
9) Fikstür yoğunluğu, dinlenme süresi ve yakın maç yükü.
10) UEFA/turnuva puan durumu ve maçın iki takım için önemi.
11) Tur/lig aşaması durumu: garantileme, eleme sınırı, puan ihtiyacı ve olası beraberlik/galibiyet ihtiyacı.
12) Rotasyon ihtimali ve teknik direktörün rotasyon niyeti.
13) UEFA'ya bildirilmiş resmi kadro bilgisi bulunabiliyorsa belirt.
14) Resmi ilk 11 açıklanmışsa kesin olarak belirt; açıklanmamışsa null yaz.

ÇOK ÖNEMLİ: Araştırma sonucu sadece bilgi deposu değildir. Sonuç bölümünde skor tahminini değiştirebilecek 5-8 somut faktörü önem sırasıyla yaz.
Çelişen kaynakları conflicts alanında belirt. Kaynak adlarını sources alanına yaz.

SADECE JSON:
{{
 "summary":"en fazla 1000 karakter",
 "home":{{"form":"","goals_trend":"","xg_xga":"","shots":"","home_away":"","injuries_suspensions":"","last_match_squad":"","probable_xi":"","key_players":"","tactics":""}},
 "away":{{"form":"","goals_trend":"","xg_xga":"","shots":"","home_away":"","injuries_suspensions":"","last_match_squad":"","probable_xi":"","key_players":"","tactics":""}},
 "league_context":{{"home_league":"","away_league":"","home_league_strength":"","away_league_strength":"","european_level":"","comparison":""}},
 "opponent_quality":{{"home":"","away":"","comparison":""}},
 "fixture_congestion":{{"home":"","away":"","comparison":""}},
 "motivation":{{"home":"","away":"","qualification_context":"","points_needed":""}},
 "rotation_risk":{{"home":"","away":"","reasons":""}},
 "official_squad":{{"home":"","away":"","status":"NOT_FOUND|FOUND"}},
 "official_xi":{{"home":null,"away":null,"status":"NOT_ANNOUNCED|ANNOUNCED"}},
 "comparison":"en önemli maç içi farklar",
 "score_drivers":["skoru etkileyebilecek en önemli faktör"],
 "news":[""], "conflicts":[""], "sources":["kaynak adı - URL"],
 "research_confidence":"HIGH|MEDIUM|LOW"
}}
"""
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        response_mime_type="application/json",
        temperature=0.15,
        max_output_tokens=5200,
    )
    # Search grounding için Gemini 2.5 Flash kullanılır. Gemini 3.x API
    # ücretsiz katmanda Google Search grounding sunmadığı için 429 alınabilir.
    # 2.5 Flash Search grounding için ücretsiz günlük limit sunar.
    import time

    last_error = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(model=RESEARCH_MODEL, contents=prompt, config=config)
            break
        except Exception as error:
            last_error = error
            message = str(error)
            if ("429" not in message and "RESOURCE_EXHAUSTED" not in message and
                    "503" not in message and "UNAVAILABLE" not in message):
                raise
            if attempt < 2:
                time.sleep(2 ** attempt * 2)
    else:
        raise last_error
    result = _extract_json(response.text or "")
    result["status"] = "OK"
    result["researched_at"] = datetime.now(timezone.utc).isoformat()
    return result
