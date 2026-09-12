from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

@dataclass
class AIVote:
    model: str
    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None

GEMINI_MODEL = "gemini-3.6-flash"
MISTRAL_MODEL = "mistral-small-latest"
GROQ_QWEN_MODEL = "qwen/qwen3.6-27b"
GROQ_120B_MODEL = "openai/gpt-oss-120b"
COHERE_MODEL = "command-a-plus-05-2026"

# Rate-limit / transient error retry settings (free-tier friendly)
_MAX_RETRIES = 4
_BASE_WAIT_SEC = 2.0


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    markers = (
        "429",
        "rate limit",
        "rate_limited",
        "resource_exhausted",
        "quota",
        "too many requests",
        "503",
        "unavailable",
        "high demand",
        "overloaded",
    )
    return any(m in text for m in markers)


def _call_with_retry(name: str, fn: Callable[[], str], max_retries: int = _MAX_RETRIES) -> str:
    """Call fn with exponential backoff on rate-limit / transient errors."""
    last_error: BaseException | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if not _is_rate_limit_error(exc) or attempt >= max_retries - 1:
                raise
            wait = (_BASE_WAIT_SEC * (2 ** attempt)) + random.uniform(0, 1.0)
            print(f"⏳ {name} rate-limit/transient hata (deneme {attempt + 1}/{max_retries}), {wait:.1f}s bekleniyor...")
            time.sleep(wait)
    raise last_error  # type: ignore[misc]


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("AI cevabı JSON değil.")
        return json.loads(match.group(0))


def _normalize(result: dict[str, Any], home: str, away: str) -> dict[str, Any]:
    outcome = str(result.get("outcome", "")).upper().strip()
    if outcome not in {"HOME", "DRAW", "AWAY"}:
        raise ValueError(f"Geçersiz outcome: {outcome}")
    score = str(result.get("score", "")).strip()
    match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", score)
    if not match:
        raise ValueError(f"Geçersiz skor: {score}")
    home_goals, away_goals = int(match.group(1)), int(match.group(2))
    if outcome == "HOME" and home_goals <= away_goals:
        raise ValueError("HOME sonucu ile skor yönü uyuşmuyor.")
    if outcome == "AWAY" and away_goals <= home_goals:
        raise ValueError("AWAY sonucu ile skor yönü uyuşmuyor.")
    if outcome == "DRAW" and home_goals != away_goals:
        raise ValueError("DRAW sonucu ile skor yönü uyuşmuyor.")
    confidence = int(result.get("confidence", 0))
    if not 0 <= confidence <= 100:
        raise ValueError("confidence 0-100 aralığında olmalı.")
    reasons = result.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = [str(reasons)]
    candidates = result.get("score_candidates", [])
    if not isinstance(candidates, list):
        candidates = []
    return {
        "home_team": home, "away_team": away, "outcome": outcome, "score": score,
        "confidence": confidence, "reasons": [str(x) for x in reasons[:5]],
        "score_candidates": [str(x) for x in candidates[:3]],
        "change_vs_previous": str(result.get("change_vs_previous", "")),
    }


def build_prompt(home: str, away: str, match_context: dict[str, Any], research: dict[str, Any], history: dict[str, Any] | None) -> str:
    context_text = json.dumps(match_context, ensure_ascii=False, separators=(",", ":"))[:8500]
    research_text = json.dumps(research, ensure_ascii=False, separators=(",", ":"))[:9000]
    history_text = json.dumps(history or {}, ensure_ascii=False, separators=(",", ":"))[:2500]
    return f"""
Sen profesyonel UEFA Champions League maç analistisin. Amacın 1X2 tahmininden çok, mümkün olan en isabetli TAM SKOR tahminini üretmektir.
Maç: {home} - {away}

YAPILANDIRILMIŞ VERİ:
{context_text}

GÜNCEL ARAŞTIRMA:
{research_text}

ARŞİV / GEÇMİŞ:
{history_text}

KARAR PROTOKOLÜ — ATLANMAYACAK:
1) Takım gücünü sadece son 5 sonuca göre değerlendirme; rakiplerin seviyesi ve rakiplerin lig/Avrupa kalitesini hesaba kat.
2) Kendi liglerinin kalite farkını ve Avrupa seviyesini dikkate al.
3) Genel formu, özellikle mevcut maçın ev/deplasman koşuluyla birlikte değerlendir.
4) Son 5 rakip kalitesini, gol üretimini/gol yemeyi, varsa xG/xGA ve şutları birlikte değerlendir.
5) Sakatlık, ceza, muhtemel XI, önemli oyuncuların formu ve rotasyonu skorun gol tarafını etkileyebilir.
6) Teknik direktör, taktik eşleşme ve rakibin oyun tarzını değerlendir.
7) Dinlenme/fikstür yükü ve maçın turnuva bağlamını hesaba kat.
8) Resmi ilk 11 araştırmada açıklanmışsa onu önceliklendir. Açıklanmamışsa uydurma.
9) Önce her takımın beklenen gol seviyesini zihinsel olarak belirle; sonra en olası birkaç skor arasından TEK nihai skor seç.
10) Nihai skor ile outcome mutlaka aynı yönde olmalı: ilk sayı EV SAHİBİ, ikinci sayı DEPLASMAN.
11) Tek bir faktöre aşırı ağırlık verme. Çelişkili verileri tart ve en güçlü ortak sinyali seç.

SKOR ÖNCELİĞİ:
- Öncelik exact score'dur.
- score_candidates alanına en fazla 3 makul skor yaz; ilk sıraya nihai skora en yakın alternatifleri koy.
- confidence gerçek olasılık değildir; yalnızca kendi tahminine öznel güvenindir.
- Geçmiş puan sistemi tahmini zorlayamaz; geçmiş AI performansı yalnızca yardımcı bağlamdır.

SADECE JSON:
{{"outcome":"HOME|DRAW|AWAY","score":"2-1","confidence":0,
"score_candidates":["2-1","1-1","2-0"],
"reasons":["skoru etkileyen neden 1","neden 2","neden 3","neden 4"],
"change_vs_previous":"önceki tahmin yoksa yok; değiştiyse neden"}}
"""


def _gemini(prompt: str) -> str:
    from google import genai

    def _once() -> str:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.15,
                "max_output_tokens": 1100,
            },
        )
        return response.text or ""

    return _call_with_retry("Gemini", _once)


def _mistral(prompt: str) -> str:
    from mistralai.client import Mistral

    def _once() -> str:
        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
        response = client.chat.complete(
            model=MISTRAL_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=1100,
        )
        return response.choices[0].message.content or ""

    return _call_with_retry("Mistral", _once)


def _groq(prompt: str, model: str) -> str:
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(model=model,
        messages=[{"role":"user","content":prompt}], temperature=0.1,
        max_completion_tokens=1100, response_format={"type":"json_object"},
        reasoning_effort="low" if model == GROQ_120B_MODEL else "none")
    return response.choices[0].message.content or ""


def _cohere(prompt: str) -> str:
    import cohere
    client = cohere.ClientV2(api_key=os.environ["COHERE_API_KEY"])
    response = client.chat(model=COHERE_MODEL, messages=[{"role":"user","content":prompt}])
    return "\n".join(getattr(block, "text", "") for block in (getattr(response.message, "content", []) or []) if getattr(block, "type", "") == "text")


def run_ai_pool(home: str, away: str, match_context: dict[str, Any], research: dict[str, Any], history: dict[str, Any] | None) -> list[AIVote]:
    prompt = build_prompt(home, away, match_context, research, history)
    providers: list[tuple[str, Callable[[str], str], str]] = [
        ("Gemini 3.6 Flash", _gemini, "GEMINI_API_KEY"),
        ("Mistral Small Latest", _mistral, "MISTRAL_API_KEY"),
        ("Groq Qwen 3.6 27B", lambda p: _groq(p, GROQ_QWEN_MODEL), "GROQ_API_KEY"),
        ("Cohere Command A+", _cohere, "COHERE_API_KEY"),
        ("Groq GPT-OSS 120B", lambda p: _groq(p, GROQ_120B_MODEL), "GROQ_API_KEY"),
    ]
    votes: list[AIVote] = []
    for idx, (name, call, key_name) in enumerate(providers):
        if not os.environ.get(key_name):
            votes.append(AIVote(name, False, error=f"{key_name} eksik"))
            continue
        # Free-tier friendly: short pause between different providers
        if idx > 0:
            time.sleep(1.5)
        try:
            parsed = _normalize(_extract_json(call(prompt)), home, away)
            votes.append(AIVote(name, True, parsed))
            print(f"✅ {name}: {parsed['outcome']} / {parsed['score']}")
        except Exception as error:
            votes.append(AIVote(name, False, error=str(error)))
            print(f"⚠️ {name} başarısız: {error}")
    return votes
