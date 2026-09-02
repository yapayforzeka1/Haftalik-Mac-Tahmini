from __future__ import annotations

import json
import os
import re
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

    home_goals = int(match.group(1))
    away_goals = int(match.group(2))

    # Skor sırası kesin olarak EV SAHİBİ - DEPLASMAN şeklindedir.
    # HOME → ev sahibi daha fazla gol atmalı.
    # AWAY → deplasman daha fazla gol atmalı.
    # DRAW → iki takımın golü eşit olmalı.
    if outcome == "HOME" and home_goals <= away_goals:
        raise ValueError(
            f"HOME tahmini ile skor uyuşmuyor: {score} "
            f"({home} ev sahibi, {away} deplasman)"
        )

    if outcome == "AWAY" and away_goals <= home_goals:
        raise ValueError(
            f"AWAY tahmini ile skor uyuşmuyor: {score} "
            f"({home} ev sahibi, {away} deplasman)"
        )

    if outcome == "DRAW" and home_goals != away_goals:
        raise ValueError(
            f"DRAW tahmini ile skor uyuşmuyor: {score}"
        )

    score = f"{home_goals}-{away_goals}"
    confidence = int(result.get("confidence", 0))
    if not 0 <= confidence <= 100:
        raise ValueError("confidence 0-100 aralığında olmalı.")
    reasons = result.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = [str(reasons)]
    return {
        "home_team": home, "away_team": away, "outcome": outcome, "score": score,
        "confidence": confidence, "reasons": [str(x) for x in reasons[:4]],
        "change_vs_previous": str(result.get("change_vs_previous", "")),
    }


def build_prompt(home: str, away: str, match_context: dict[str, Any], research: dict[str, Any], history: dict[str, Any] | None) -> str:
    # Keep provider prompts bounded so Groq/Mistral do not receive an unnecessarily huge request.
    context_text = json.dumps(match_context, ensure_ascii=False, separators=(",", ":"))[:9000]
    research_text = json.dumps(research, ensure_ascii=False, separators=(",", ":"))[:8500]
    history_text = json.dumps(history or {}, ensure_ascii=False, separators=(",", ":"))[:2500]
    return f"""
Sen profesyonel UEFA Champions League maç analistisin.
Maç: {home} - {away}

Yapılandırılmış futbol verisi:
{context_text}

Güncel araştırma:
{research_text}

Arşiv/haftalık geçmiş:
{history_text}

Form, gol trendi, xG/xGA ve şutlar mevcutsa, sakatlık/ceza, muhtemel XI,
oyuncu formu, taktik eşleşme, iç/dış saha, UEFA sıralaması ve fikstür bağlamını
birlikte değerlendir. Veri yoksa tahmin uydurma.

Farklı görüşler normaldir. Tahminini kısa ve somut nedenlerle savun.
"confidence" gerçek olasılık değildir; öznel güven puanıdır.

ÇOK ÖNEMLİ SKOR YÖNÜ KURALI:
- Maç: {home} - {away}
- İlk skor EV SAHİBİNİN gol sayısıdır: {home}
- İkinci skor DEPLASMANIN gol sayısıdır: {away}
- HOME seçersen skor mutlaka ev sahibi lehine olmalıdır.
- AWAY seçersen skor mutlaka deplasman lehine olmalıdır.
- DRAW seçersen iki skor eşit olmalıdır.
- Örnek: {home} kazanırsa 2-1, 3-1 veya 1-0.
- {away} kazanırsa 1-2, 0-2 veya 1-3.
- Beraberlik ise 0-0, 1-1, 2-2 gibi eşit skor olmalıdır.
- Skoru ASLA kazanan takımın adına göre ters çevirme.

SADECE JSON:
{{"outcome":"HOME|DRAW|AWAY","score":"2-1","confidence":0,
"reasons":["neden 1","neden 2","neden 3"],
"change_vs_previous":"önceki tahmin yoksa yok; değiştiyse neden"}}
"""


def _gemini(prompt: str) -> str:
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt,
        config={"response_mime_type": "application/json", "temperature": 0.2, "max_output_tokens": 900})
    return response.text or ""


def _mistral(prompt: str) -> str:
    from mistralai.client import Mistral
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    response = client.chat.complete(model=MISTRAL_MODEL, messages=[{"role":"user","content":prompt}],
        temperature=0.1, response_format={"type":"json_object"}, max_tokens=900)
    return response.choices[0].message.content or ""


def _groq(prompt: str, model: str) -> str:
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(model=model,
        messages=[{"role":"user","content":prompt}], temperature=0.1,
        max_completion_tokens=900, response_format={"type":"json_object"},
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
    for name, call, key_name in providers:
        if not os.environ.get(key_name):
            votes.append(AIVote(name, False, error=f"{key_name} eksik")); continue
        try:
            parsed = _normalize(_extract_json(call(prompt)), home, away)
            votes.append(AIVote(name, True, parsed))
            print(f"✅ {name}: {parsed['outcome']} / {parsed['score']}")
        except Exception as error:
            votes.append(AIVote(name, False, error=str(error)))
            print(f"⚠️ {name} başarısız: {error}")
    return votes
