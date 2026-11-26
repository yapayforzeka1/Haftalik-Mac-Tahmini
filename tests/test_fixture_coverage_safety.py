from datetime import datetime, timezone

from v2_context import enrich_team_context, safe_model_inputs


def test_partial_history_never_claims_complete_rest_or_congestion():
    form = {'matches': [{'date': '2026-11-04T20:00:00Z', 'venue': 'AWAY',
                         'competition': 'UEFA Champions League'}]}
    result = enrich_team_context(form, datetime(2026, 11, 25, 20, tzinfo=timezone.utc))
    assert result['match_history_coverage'] == 'UNVERIFIED'
    assert result['rest_days_before_match'] is None
    assert result['matches_last_14_days'] is None
    assert result['matches_last_21_days'] is None


def test_legacy_cached_context_is_sanitized_without_mutating_record():
    context = {'home': {'last_5': {'matches': [], 'rest_days_before_match': 21,
                                   'matches_last_14_days': 0}}, 'away': {}}
    research = {'fixture_congestion': {'home': '21 gün dinlenme', 'away': '3 gün'}}
    safe_context, safe_research = safe_model_inputs(context, research)
    assert safe_context['home']['last_5']['rest_days_before_match'] is None
    assert '21 gün' not in safe_research['fixture_congestion']['home']
    assert context['home']['last_5']['rest_days_before_match'] == 21


def test_confirmed_complete_coverage_keeps_values():
    context = {'home': {'last_5': {'match_history_coverage': 'COMPLETE',
                                   'rest_days_before_match': 3}}}
    research = {'fixture_congestion': {'home': '3 gün dinlenme'}}
    safe_context, safe_research = safe_model_inputs(context, research)
    assert safe_context['home']['last_5']['rest_days_before_match'] == 3
    assert safe_research['fixture_congestion']['home'] == '3 gün dinlenme'
