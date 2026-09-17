"""Deterministic post-match audit and bounded, approval-only prompt policies.

Feature buckets are associations, NOT causal attribution. No extra LLM calls.
Archived inputs are the only evidence; historical matches are not re-researched.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone

from scoring import VERSION, outcome, parse_score, score_prediction

POLICIES = {
    "balanced_v1": "Tam skor önceliklidir. Verileri dengeli tart; eksik veriyi uydurma.",
    "lineup_caution_v1": (
        "Tam skor önceliklidir. Resmi XI yoksa tahmini XI kesin bilgi değildir. "
        "Kadro belirsizliğinde isimlere dayanan çıkarımları azalt; doğrulanmış takım "
        "formuna ve gol üretimine dayan. Sırf belirsizlik var diye beraberlik seçme."
    ),
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def new_state():
    return {"schema": 1, "policy": "balanced_v1", "revision": 0, "proposals": {},
            "decisions": [], "update_offset": 0, "notices": {}, "summaries": {}}


def features(record):
    context = record.get("context") or {}
    research = record.get("research") or {}
    return {
        "official_xi": (context.get("official_xi") or {}).get("status") == "ANNOUNCED",
        "research_available": research.get("status") == "OK",
        "home_form": bool((context.get("home", {}).get("last_5") or {}).get("matches")),
        "away_form": bool((context.get("away", {}).get("last_5") or {}).get("matches")),
        "standings": bool(context.get("home", {}).get("standings") and context.get("away", {}).get("standings")),
    }


def audit(record):
    actual = record.get("actual") or {}
    if actual.get("home") is None or actual.get("away") is None:
        return None
    ah, aa = actual["home"], actual["away"]
    rows = []
    for vote in record.get("ai_votes", []):
        result = vote.get("result") or {}
        score = parse_score(result.get("score"))
        if not vote.get("success") or score is None:
            rows.append({"model": vote.get("model"), "available": False})
            continue
        ph, pa = score
        rows.append({"model": vote["model"], "available": True,
                     "points": score_prediction(result["score"], ah, aa),
                     "exact": score == (ah, aa), "outcome_correct": outcome(ph, pa) == outcome(ah, aa),
                     "goal_error": abs(ph-ah) + abs(pa-aa),
                     "home_bias": ph-ah, "away_bias": pa-aa,
                     "factors_used": result.get("factors_used", []),
                     "pre_match_reasons": result.get("reasons", [])})
    return {"version": VERSION, "features": features(record), "models": rows,
            "policy": record.get("learning_policy", "legacy"),
            "evidence_hash": digest({"votes": record.get("ai_votes"), "actual": actual,
                                     "context": record.get("context"), "research": record.get("research")}),
            "interpretation": "Birlikte görülme ölçümüdür; veri etkisinin nedensel kanıtı değildir."}


def summarize(predictions):
    stats = defaultdict(lambda: {"opportunities": 0, "available": 0, "points": 0,
                                 "exact": 0, "outcome": 0, "goal_error": 0})
    buckets = defaultdict(lambda: {"matches": 0, "exact_matches": 0})
    fallback = {"matches": 0, "points": 0, "exact": 0}
    for r in predictions.values():
        if r.get('prediction_kind') == 'STATISTICAL' and r.get('fallback_points') is not None:
            fallback['matches'] += 1
            fallback['points'] += r['fallback_points']
            fallback['exact'] += r['fallback_points'] == 6
        review = r.get("post_match_analysis")
        if not review:
            continue
        for row in review["models"]:
            s = stats[row["model"]]
            s["opportunities"] += 1
            if row["available"]:
                s["available"] += 1
                s["points"] += row["points"]
                s["exact"] += row["exact"]
                s["outcome"] += row["outcome_correct"]
                s["goal_error"] += row["goal_error"]
        # One independent unit per match, not one per correlated model vote.
        if any(row["available"] for row in review["models"]):
            for feature, present in review["features"].items():
                b = buckets[f"{feature}={present}"]
                b["matches"] += 1
                b["exact_matches"] += any(row.get("exact") for row in review["models"])
    for s in stats.values():
        n = s["available"]
        s["coverage_pct"] = round(100*n/s["opportunities"], 1) if s["opportunities"] else 0
        s["exact_pct"] = round(100*s["exact"]/n, 1) if n else None
        s["outcome_pct"] = round(100*s["outcome"]/n, 1) if n else None
        s["avg_points"] = round(s["points"]/n, 2) if n else None
        s["mean_goal_error"] = round(s["goal_error"]/n, 2) if n else None
    return {"scoring": VERSION, "models": dict(stats), "feature_associations": dict(buckets),
            "statistical_fallback": fallback, "declared_factor_associations": factor_summary(predictions)}


def factor_summary(predictions):
    """Explicit model-declared factor use, without inferring it from prose."""
    result = defaultdict(lambda: {'used': 0, 'exact': 0, 'outcome_correct': 0, 'goal_error': 0})
    for record in predictions.values():
        for row in (record.get('post_match_analysis') or {}).get('models', []):
            if not row.get('available'):
                continue
            for factor in set(row.get('factors_used', [])):
                item = result[f"{row['model']}:{factor}"]
                item['used'] += 1
                for field in ('exact', 'outcome_correct', 'goal_error'):
                    item[field] += row[field]
    return dict(result)


def eligible(record, before=None):
    # Legacy predictions remain in rankings but cannot establish pre-match provenance.
    if record.get("prediction_kind", "AI") != "AI" or not record.get("prediction_created_at"):
        return False
    try:
        created = datetime.fromisoformat(record["prediction_created_at"].replace("Z", "+00:00"))
        kickoff = datetime.fromisoformat(record["match_utc"].replace("Z", "+00:00"))
        if created >= kickoff:
            return False
        if before:
            resolved = datetime.fromisoformat(record["actual"]["updated_at"].replace("Z", "+00:00"))
            return resolved < before and kickoff < before
        return True
    except (KeyError, TypeError, ValueError):
        return False


def maybe_propose(predictions, state):
    """Propose a bounded experiment, never assert untested prompt efficacy."""
    if state['policy'] == 'lineup_caution_v1':
        maybe_propose_rollback(predictions, state)
        return
    if any(p["policy"] == "lineup_caution_v1" for p in state["proposals"].values()):
        return
    records = sorted((r for r in predictions.values() if eligible(r) and r.get("post_match_analysis")),
                     key=lambda r: r["match_utc"])
    without = [r for r in records if not r["post_match_analysis"]["features"]["official_xi"]]
    with_xi = [r for r in records if r["post_match_analysis"]["features"]["official_xi"]]
    if min(len(without), len(with_xi)) < 8:
        return
    def rate(rows):
        return sum(any(v.get("exact") for v in r["post_match_analysis"]["models"]) for r in rows)/len(rows)
    gap = rate(with_xi) - rate(without)
    if gap < .15:
        return
    evidence = {"with_xi_matches": len(with_xi), "without_xi_matches": len(without),
                "with_xi_any_exact_rate": round(rate(with_xi), 3),
                "without_xi_any_exact_rate": round(rate(without), 3),
                "match_ids": [r["match_id"] for r in records],
                "limitation": "Gözlemsel fark; rakip gücü ve maç zorluğu kontrol edilmedi. "
                              "Yeni talimatın başarı artışı henüz test edilmedi; sınırlı deney önerisi."}
    proposal_id = digest(evidence)[:12]
    state["proposals"][proposal_id] = {
        "id": proposal_id, "status": "PENDING", "created_at": utcnow(),
        "base_revision": state["revision"], "previous_policy": state["policy"],
        "policy": "lineup_caution_v1", "instruction": POLICIES["lineup_caution_v1"],
        "reason": "Resmi XI bulunmayan maçlarda tam skor isabeti daha düşük gözlendi.",
        "evidence": evidence, "notified": False,
    }


def maybe_propose_rollback(predictions, state):
    """A deterioration can propose reverting, but never bypasses admin approval."""
    if any(p['base_revision'] == state['revision'] and p['policy'] == 'balanced_v1'
           for p in state['proposals'].values()):
        return
    records = [r for r in predictions.values() if eligible(r) and r.get('post_match_analysis')
               and not r['post_match_analysis']['features']['official_xi']]
    old = sorted([r for r in records if r.get('learning_policy') == 'balanced_v1'], key=lambda r:r['match_utc'])[-16:]
    new = sorted([r for r in records if r.get('learning_policy') == 'lineup_caution_v1'
                  and r.get('policy_revision') == state['revision']], key=lambda r:r['match_utc'])[-16:]
    if min(len(old), len(new)) < 8:
        return
    def rate(rows):
        return sum(any(v.get('exact') for v in r['post_match_analysis']['models']) for r in rows)/len(rows)
    state['policy_monitor'] = {'old_matches':len(old),'new_matches':len(new),
                               'old_exact_rate':rate(old),'new_exact_rate':rate(new)}
    if rate(old) - rate(new) < .15:
        return
    evidence = {'with_xi_matches':len(old), 'without_xi_matches':len(new),
        'with_xi_any_exact_rate':rate(old),'without_xi_any_exact_rate':rate(new),
        'group_a':'Önceki politika (XI yok)', 'group_b':'Yeni politika (XI yok)',
        'match_ids':[r['match_id'] for r in old+new],
        'limitation':'İleriye dönük gözlemsel karşılaştırma; farklı maçlar ve model erişimi nedeniyle nedensellik kanıtlanmaz.'}
    pid = digest([state['revision'], evidence])[:12]
    state['proposals'][pid] = {'id':pid,'status':'PENDING','created_at':utcnow(),
        'base_revision':state['revision'],'previous_policy':state['policy'],'policy':'balanced_v1',
        'instruction':POLICIES['balanced_v1'],'reason':'Yeni politika sonrasında tam skor isabetinde düşüş gözlendi; önceki ayara dönüş önerisi.',
        'evidence':evidence,'notified':False}


def learning_context(predictions, state, kickoff):
    prior = {k: r for k, r in predictions.items() if eligible(r, kickoff) and r.get("post_match_analysis")}
    summary = summarize(prior)
    return {"policy": state["policy"], "instruction": POLICIES[state["policy"]],
            "historical_matches": len(prior), "models": summary["models"],
            "feature_associations": summary["feature_associations"],
            "declared_factor_associations": dict(sorted(factor_summary(prior).items(),
                key=lambda item:item[1]['used'], reverse=True)[:10]),
            "warning": "Örneklem küçük olabilir. Korelasyon neden değildir; geçmiş sonuçları kopyalama."}
