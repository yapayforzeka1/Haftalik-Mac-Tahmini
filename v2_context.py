from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from copy import deepcopy


def safe_model_inputs(context: dict, research: dict) -> tuple[dict, dict]:
    """Remove inferred rest from legacy or incomplete fixture snapshots."""
    context, research = deepcopy(context or {}), deepcopy(research or {})
    congestion = research.get('fixture_congestion')
    for side in ('home', 'away'):
        team = context.get(side) or {}
        form = team.get('last_5') or {}
        if not isinstance(form, dict) or form.get('match_history_coverage') != 'COMPLETE':
            if isinstance(form, dict):
                for key in ('rest_days_before_match', 'matches_last_14_days', 'matches_last_21_days'):
                    form[key] = None
                form['match_history_coverage'] = 'UNVERIFIED'
            if isinstance(congestion, dict):
                congestion[side] = 'Maç geçmişi eksik olabilir; dinlenme süresi ve maç yoğunluğu bilinmiyor.'
    return context, research


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def enrich_team_context(form: dict[str, Any], kickoff: datetime) -> dict[str, Any]:
    matches = form.get('matches', [])
    home = [m for m in matches if m.get('venue') == 'HOME']
    away = [m for m in matches if m.get('venue') == 'AWAY']

    def split(rows: list[dict[str, Any]]) -> dict[str, Any]:
        gf = sum(int(m.get('goals_for', 0) or 0) for m in rows)
        ga = sum(int(m.get('goals_against', 0) or 0) for m in rows)
        wins = sum(m.get('result') == 'W' for m in rows)
        draws = sum(m.get('result') == 'D' for m in rows)
        losses = sum(m.get('result') == 'L' for m in rows)
        return {
            'matches': len(rows),
            'record': f'{wins}W-{draws}D-{losses}L',
            'goals_for': gf,
            'goals_against': ga,
            'avg_goals_for': round(gf / len(rows), 2) if rows else None,
            'avg_goals_against': round(ga / len(rows), 2) if rows else None,
        }

    enriched = dict(form)
    enriched['home_split_last_5'] = split(home[:5])
    enriched['away_split_last_5'] = split(away[:5])
    # The provider's list can omit whole competitions. Even a recent match or
    # five returned rows cannot establish that no other match was played.
    # Expose observations as such; do not present them as complete workload.
    enriched['match_history_coverage'] = 'UNVERIFIED'
    enriched['rest_days_before_match'] = None
    enriched['matches_last_14_days'] = None
    enriched['matches_last_21_days'] = None
    return enriched
