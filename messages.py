"""Approved prediction tables, shared by archive text and Telegram image."""
from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from experimental_scores import eligible_score_votes

FORMAT_VERSION = 4
MODEL_COUNT = 5


def label(value, record):
    return {"HOME": record["home_team"], "AWAY": record["away_team"], "DRAW": "Beraberlik"}.get(value, "—")


def short_model(name):
    name = str(name)
    for token, short in (("gemini", "Gemini"), ("mistral", "Mistral"), ("qwen", "Qwen"),
                         ("cohere", "Cohere"), ("gpt-oss", "GPT-OSS"), ("clef", "Clef")):
        if token in name.lower():
            return short
    return name


def short_reason(result):
    reason = result.get("short_reason")
    if not reason:
        reasons = result.get("reasons") or []
        reason = reasons[0] if isinstance(reasons, list) and reasons else reasons
    text = " ".join(str(reason or "").split())
    if not text:
        return "Gerekçe belirtilmedi."
    clipped = " ".join(text.split()[:9])
    if len(clipped) > 72:
        clipped = clipped[:69].rsplit(" ", 1)[0]
    return clipped + ("…" if clipped != text else "")


def kickoff_text(record):
    if record.get("match_utc"):
        dt = datetime.fromisoformat(record["match_utc"].replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("Europe/Istanbul")).strftime("%H:%M TSİ")
    return str(record.get("match_time", "—")).split()[-1] + " TSİ"


def lineup_text(record):
    context = record.get("context") or {}
    from providers import valid_xi
    official = context.get("official_xi") or {}
    predicted = context.get("predicted_xi") or {}
    kinds = []
    for side in ("home", "away"):
        if valid_xi(official.get(side)):
            kinds.append("OFFICIAL")
        elif valid_xi(predicted.get(side)):
            kinds.append("PREDICTED")
        else:
            kinds.append("MISSING")
    if kinds == ["OFFICIAL", "OFFICIAL"]:
        return "✅ Resmî 11"
    if kinds == ["PREDICTED", "PREDICTED"]:
        return "⚠️ Tahmini 11"
    if set(kinds) == {"OFFICIAL", "PREDICTED"}:
        return "⚠️ Karma 11 (resmî/tahmini)"
    return "⚠️ Kadro eksik"


def _is_prediction_complete(record):
    if 'prediction_complete' in record:
        return bool(record.get('prediction_complete'))
    successful = {v.get('model') for v in record.get('ai_votes', [])
                  if v.get('success') and isinstance(v.get('result'), dict) and v.get('model')}
    return len(successful) >= MODEL_COUNT


def prediction_tables(record):
    """JSON-safe presentation; individual AI records are never modified."""
    votes = [v for v in record.get("ai_votes", []) if v.get("success") and v.get("result")]
    if record.get("prediction_kind") in {"UNAVAILABLE", "STATISTICAL"}:
        votes = []
    n = len(votes)
    valid_score_count = len(eligible_score_votes(record.get("ai_votes")))
    total = max(MODEL_COUNT, len(record.get("ai_votes", [])), int(record.get("total_ai") or 0))
    match = f"{record['home_team']} – {record['away_team']}"
    clock = kickoff_text(record)
    if not n:
        complete = _is_prediction_complete(record)
        note = '' if complete else f'⚠️ KISMİ DURUM: {valid_score_count}/{total} AL tahmin üretti; başarısız modeller kontrollü aralıklarla yeniden denenecek.'
        return {"mode": "UNAVAILABLE", "summary_headers": ["⚽ Maç", "🕒 Saat", "🤖 Başarılı Tahmin Üreten AL", "📋 Durum"],
                "summary": [match, clock, f"0/{total}", "⚠️ Tahmin üretilemedi"],
                "headers": [], "rows": [], "note": note}
    counts = Counter(v['result']['score'] for v in votes)
    outcomes = Counter(v['result']['outcome'] for v in votes)
    outcome, ov = outcomes.most_common(1)[0]
    score, sv = counts.most_common(1)[0]
    common_outcome = ov >= 3
    common_score = common_outcome and sv >= 3 and all(v["result"]["outcome"] == outcome for v in votes if v["result"]["score"] == score)
    mode = ('INDIVIDUAL' if n < 3 else 'NORMAL' if common_score else
            'OUTCOME_COMMON_SCORE_SPLIT' if common_outcome else 'NO_COMMON')
    table = {"mode": mode, "summary_headers": ["⚽ Maç", "🕒 Saat", "📋 Durum"],
             "summary": [match, clock, lineup_text(record)], "headers": [], "rows": [], "note": ""}
    table['summary_headers'] += ['🤖 Başarılı Tahmin Üreten AL']
    table['summary'] += [f'{valid_score_count}/{total}']
    complete = _is_prediction_complete(record)
    if n < 3:
        table['note'] = '⚠️ Üçten az AI yanıtladı; bireysel tahminler gösteriliyor.'
    else:
        table['summary_headers'] += ['🏆 Ortak tahmin', '🎯 Ortak skor']
        table['summary'] += [f'{label(outcome, record)} · {ov}/{n}' if common_outcome else 'Yok',
                             f'{score.replace("-", "–")} · {sv}/{n}' if common_score else 'Yok']
    if mode == 'NORMAL':
        table['summary_headers'] += ['🤖 Skoru seçen AI’lar']
        table['summary'] += [', '.join(short_model(v['model']) for v in votes if v['result']['score'] == score)]
    elif mode == 'OUTCOME_COMMON_SCORE_SPLIT':
        table['headers'] = ['🤖 AI Modelleri', '🎯 Skor', 'Oy']
        groups = defaultdict(list)
        for v in votes:
            groups[v['result']['score']].append(short_model(v['model']))
        table['rows'] = [[', '.join(groups[s]), s.replace('-', '–'), f'{count}/{n}'] for s, count in counts.most_common()]
    else:
        table['headers'] = ['🤖 AI', '🏆 Kazanan ve kısa sebep', '🎯 Skor'] + (['Oy'] if n >= 3 else [])
        for v in votes:
            result = v['result']
            row = [short_model(v['model']), f"{label(result['outcome'], record)} — {short_reason(result)}",
                   result['score'].replace('-', '–')]
            if n >= 3:
                row += [f"{counts[result['score']]}/{n}"]
            table['rows'].append(row)
    if not complete:
        if common_outcome:
            status_note = f'⚠️ GEÇİCİ ORTAK KARAR: {label(outcome, record)} ({ov}/{n} geçerli oy); toplam {valid_score_count}/{total} AL yanıtladı. Eksik AL tahminleri yeniden denenecek.'
        else:
            status_note = f'⚠️ KISMİ TAHMİN: {valid_score_count}/{total} AL yanıtladı; 5/5 tamamlanmadı.'
        table['note'] = ' '.join(x for x in (table.get('note', ''), status_note) if x)
    return table


def prediction_message(record):
    """Plain-text archive equivalent; new Telegram predictions use the table image."""
    table = record.get('prediction_table') or prediction_tables(record)
    lines = [' | '.join(table['summary_headers']), ' | '.join(table['summary'])]
    if table['headers']:
        lines += ['', ' | '.join(table['headers'])]
        lines += [' | '.join(row) for row in table['rows']]
    if table['note']:
        lines += ['', table['note']]
    return '\n'.join(lines)
