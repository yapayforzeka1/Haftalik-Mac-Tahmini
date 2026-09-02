from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from google import genai
from google.genai import types

RESEARCH_MODEL = "gemini-3.7-flash"


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
        "news": [], "conflicts": [reason], "sources": [],
        "research_confidence": "LOW",
        "researched_at": datetime.now(timezone.utc).isoformat(),
    }


def research_match(client: genai.Client, home_team: str, away_team: str, match_context: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""
UEFA Champions League 2026/27 maç öncesi güncel araştırma yap.
Maç: {home_team} - {away_team}
Bugün: {datetime.now(timezone.utc).date().isoformat()}

Yapılandırılmış veriler:
{_compact(match_context, 12000)}

Google Search ile güncel ve mümkün olduğunca bağımsız kaynakları çapraz kontrol et.
Öncelik: UEFA/klüp resmi kaynakları, güvenilir spor basını ve istatistik siteleri.
Son 60 gün ve son 5 resmi maça odaklan. Çelişen bilgileri conflicts alanına yaz.
Bulamadığın istatistiği uydurma; null veya "bulunamadı" kullan.

Araştırılacaklar: son 5 form, gol/gol yeme, xG/xGA varsa, şut/isabetli şut varsa,
iç saha/deplasman, sakatlık/ceza, muhtemel XI, önemli oyuncu formu, teknik direktör,
taktik eşleşme, rakip oyun tarzı, transfer/squad değişiklikleri, UEFA puan durumu ve
fikstür bağlamı, yakın tarihli güvenilir haberler.

SADECE JSON:
{{
 "summary":"en fazla 800 karakter",
 "home":{{"form":"","goals_trend":"","xg_xga":"","shots":"","home_away":"","injuries_suspensions":"","probable_xi":"","key_players":"","tactics":""}},
 "away":{{"form":"","goals_trend":"","xg_xga":"","shots":"","home_away":"","injuries_suspensions":"","probable_xi":"","key_players":"","tactics":""}},
 "comparison":"en önemli farklar",
 "news":[""],
 "conflicts":[""],
 "sources":["kaynak adı - URL"],
 "research_confidence":"HIGH|MEDIUM|LOW"
}}
"""
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        response_mime_type="application/json",
        temperature=0.2,
        max_output_tokens=4200,
    )
    response = client.models.generate_content(model=RESEARCH_MODEL, contents=prompt, config=config)
    result = _extract_json(response.text or "")
    result["status"] = "OK"
    result["researched_at"] = datetime.now(timezone.utc).isoformat()
    return result
