from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


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

    rest_days = None
    if matches:
        last = _parse_utc(matches[0].get('date'))
        if last:
            rest_days = round((kickoff - last).total_seconds() / 86400, 1)

    recent_14 = 0
    recent_21 = 0
    for m in matches:
        dt = _parse_utc(m.get('date'))
        if not dt:
            continue
        days = (kickoff - dt).total_seconds() / 86400
        if 0 <= days <= 14:
            recent_14 += 1
        if 0 <= days <= 21:
            recent_21 += 1

    enriched = dict(form)
    enriched['home_split_last_5'] = split(home[:5])
    enriched['away_split_last_5'] = split(away[:5])
    enriched['rest_days_before_match'] = rest_days
    enriched['matches_last_14_days'] = recent_14
    enriched['matches_last_21_days'] = recent_21
    return enriched
