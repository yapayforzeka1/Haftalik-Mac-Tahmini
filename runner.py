from __future__ import annotations

import copy
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ai_pool import run_ai_pool, safe_error
from consensus_engine import build_consensus
from data_provider import build_team_form, parse_utc
from history_engine import grade_record
from learning import POLICIES, audit, digest, learning_context, new_state, utcnow
from messages import FORMAT_VERSION, prediction_message, prediction_tables
from policy_sync import apply_approved_policy
from providers import (CachedFootball, merge_official_xi, merge_predicted_xi,
                       official_xi, predicted_xi, source_predicted_xi, valid_xi)
from data_provider import _normalize_team_name
from report_engine import build_result_message
from research_engine import empty_research, research_match, structured_research
from scoring import VERSION, regulation_score, score_prediction
from storage import StateError, load_json, save_json
from telegram_io import Telegram, TelegramError, deliver_text
from v2_context import enrich_team_context

ROOT = Path(__file__).resolve().parent
TURKEY = ZoneInfo("Europe/Istanbul")


def now():
    return datetime.now(timezone.utc)


def minutes_left(match):
    return (parse_utc(match['utcDate']) - now()).total_seconds()/60


# Temporarily disabled until the user reviews these clubs after the league phase.
# This filter is applied BEFORE lineup, research and AI-provider calls.
EXCLUDED_CLUBS = frozenset({"fenerbahce", "galatasaray"})


def excluded_club_name(team_name):
    """Match full club identity, including common suffixes, not partial words."""
    name = _normalize_team_name(team_name)
    return any(name == club or name.startswith(club + " ") for club in EXCLUDED_CLUBS)


def excluded_fixture(match):
    return any(excluded_club_name((match.get(side) or {}).get("name", ""))
               for side in ("homeTeam", "awayTeam"))


def excluded_record(record):
    return any(excluded_club_name(record.get(side, ""))
               for side in ("home_team", "away_team"))


def _preserve_pre_kicktipp_grade(record):
    """Capture previous points even when a still-older legacy backup exists."""
    if 'pre_kicktipp_evaluation' in record:
        return
    record['pre_kicktipp_evaluation'] = {
        'grading_version': record.get('grading_version'),
        'consensus_points': record.get('consensus_points'),
        'fallback_points': record.get('fallback_points'),
        'votes': [
            {'model': vote.get('model'), 'model_id': (vote.get('result') or {}).get('model_id'),
             'points': vote.get('points')}
            for vote in record.get('ai_votes') or [] if isinstance(vote, dict)
        ],
    }


def refresh_results(predictions, matches):
    """Regrade on verified new results, preserving previous grades and receipts."""
    by_id = {str(m['id']): m for m in matches}
    for key, r in predictions.items():
        if excluded_record(r):
            continue
        if not r.get('prediction_ready') and not r.get('final_sent'):
            continue
        match = by_id.get(key)
        if not match or match.get('status') != 'FINISHED':
            continue
        score = regulation_score(match)
        if score is None:
            r['result_warning'] = '90 dakika skoru doğrulanamadı; değerlendirme bekliyor.'
            continue
        actual = {'home': score[0], 'away': score[1], 'status': 'FINISHED', 'scope': 'REGULAR_90'}
        previous = r.get('actual') or {}
        unchanged = all(previous.get(k) == v for k, v in actual.items())
        if unchanged and r.get('grading_version') == VERSION:
            continue
        if r.get('actual') and r.get('grading_version') != VERSION:
            _preserve_pre_kicktipp_grade(r)
            if 'legacy_evaluation' not in r:
                r['legacy_evaluation'] = {k: copy.deepcopy(r.get(k)) for k in
                    ('actual', 'consensus', 'consensus_points', 'ai_votes', 'grading_version')}
        if previous and not unchanged and previous.get('scope') == 'REGULAR_90':
            r.setdefault('result_revisions', []).append(copy.deepcopy(previous))
            r['result_receipt'] = {}
            r['result_sent'] = False
            r.pop('result_text', None)
        r.setdefault('published_consensus', copy.deepcopy(r.get('consensus')))
        actual['updated_at'] = previous.get('updated_at', utcnow()) if unchanged else utcnow()
        r['actual'] = actual
        if r.get('prediction_kind', 'AI') == 'AI' and (r.get('prediction_ready') or r.get('final_sent')):
            grade_record(r)
            r['post_match_analysis'] = audit(r)
        elif r.get('prediction_kind') == 'STATISTICAL':
            r['fallback_points'] = score_prediction(r['fallback']['score'], *score)
            r['grading_version'] = VERSION
        else:
            r['grading_version'] = VERSION
        r.pop('result_warning', None)


def regrade_archived_results(predictions):
    """Migrate already verified 90-minute grades without API calls or Telegram re-sends.

    Only historical *evaluations* change. Published predictions, the original
    votes and delivery receipts remain unchanged; a one-time legacy snapshot
    keeps the pre-migration grade for audit.
    """
    count = 0
    for r in predictions.values():
        if not isinstance(r, dict) or r.get('grading_version') == VERSION:
            continue
        actual = r.get('actual') or {}
        if (actual.get('status') != 'FINISHED' or actual.get('scope') != 'REGULAR_90'
                or type(actual.get('home')) is not int or type(actual.get('away')) is not int
                or min(actual['home'], actual['away']) < 0):
            continue
        if not (r.get('prediction_ready') or r.get('final_sent')):
            continue
        _preserve_pre_kicktipp_grade(r)
        if 'legacy_evaluation' not in r:
            r['legacy_evaluation'] = {k: copy.deepcopy(r.get(k)) for k in
                ('actual', 'consensus', 'consensus_points', 'ai_votes', 'grading_version')}
        r.setdefault('published_consensus', copy.deepcopy(r.get('consensus')))
        if r.get('prediction_kind', 'AI') == 'AI':
            grade_record(r)
            r['post_match_analysis'] = audit(r)
        elif r.get('prediction_kind') == 'STATISTICAL' and isinstance(r.get('fallback'), dict):
            r['fallback_points'] = score_prediction(r['fallback'].get('score'), actual['home'], actual['away'])
            r['grading_version'] = VERSION
        else:
            r['grading_version'] = VERSION
        count += 1
    return count


def result_text(record):
    if record.get('prediction_kind', 'AI') == 'AI':
        text = build_result_message(record)
        review = record.get('post_match_analysis') or {}
        valid = [m for m in review.get('models', []) if m.get('available')]
        if valid:
            text += '\n\n🔎 Analiz: ' + '; '.join(f"{m['model']}: gol sapması {m['goal_error']}" for m in valid)
            text += '\nVeri kullanımı ve gerekçeler öğrenme arşivine kaydedildi; nedensel başarı iddiası değildir.'
        return text
    actual = record['actual']
    return (f"📊 {record['home_team']} — {record['away_team']}\n"
            f"90 dakika sonucu: {actual['home']}-{actual['away']}\n"
            f"İstatistiksel yedek puanı: {record.get('fallback_points', '—')}/8 (AI sıralamasından ayrı)")


def deliver_record(r, bot, chat_id, save, clock=None):
    """Resume each part independently; never regenerate an archived prediction."""
    if not r.get('prediction_ready') or r.get('final_sent'):
        return
    clock = clock or now
    kickoff = parse_utc(r['match_utc'])
    if r.get('message_format_version', 0) >= FORMAT_VERSION:
        # A single table image, with a durable receipt and no duplicate text.
        if r.get('photo_sent') or r.get('prediction_receipt', {}).get('complete'):
            r['final_sent'] = True
            save()
            return
        if clock() < kickoff:
            from match_report import render_match_group_image
            path = render_match_group_image([r], test_mode=bool(r.get('test_mode')))
            if clock() < kickoff:
                bot.photo(chat_id, path)
                r['photo_sent'] = True
                r['prediction_receipt'] = {'complete': True, 'transport': 'photo'}
                r['final_sent'] = True
                save()
                return
        r['delivery_expired'] = True
        r.setdefault('delivery_notice', {})
        save()
        return
    if clock() >= kickoff and not r.get('prediction_receipt', {}).get('complete'):
        r['delivery_expired'] = True
        r.setdefault('delivery_notice', {})
        text = f"⚠️ {r['home_team']} — {r['away_team']}: tahmin paketi maç başlamadan tamamen iletilemedi."
        save()
        return
    r.setdefault('prediction_receipt', {})
    if not r['prediction_receipt'].get('complete'):
        deliver_text(bot, chat_id, r['prediction_text'], r['prediction_receipt'], save)
    if r.get('image_required') and not r.get('photo_sent'):
        # Text is already persisted; image failure must not discard the prediction.
        if clock() >= kickoff:
            r['photo_skipped_after_kickoff'] = True
        else:
            from match_report import render_match_group_image
            path = render_match_group_image([r], test_mode=bool(r.get('test_mode')))
            bot.photo(chat_id, path)
            r['photo_sent'] = True
            save()
    r['final_sent'] = True
    save()


def drain_delivery(predictions, bot, chat_id, save):
    """Send new-format predictions by kickoff group, then resume results/legacy records."""
    from collections import defaultdict
    from match_report import kickoff_key, render_match_group_image

    groups = defaultdict(list)
    for r in predictions.values():
        if excluded_record(r):
            continue
        if (r.get('prediction_ready') and not r.get('final_sent')
                and r.get('message_format_version', 0) >= FORMAT_VERSION
                and not r.get('photo_sent') and not r.get('prediction_receipt', {}).get('complete')):
            try:
                if now() < parse_utc(r['match_utc']):
                    groups[(kickoff_key(r), bool(r.get('test_mode')))].append(r)
            except (KeyError, ValueError):
                pass

    for (_, is_test), records in sorted(groups.items()):
        try:
            kickoff = min(parse_utc(r['match_utc']) for r in records)
            if now() >= kickoff:
                continue
            path = render_match_group_image(records, test_mode=is_test)
            if now() >= kickoff:
                continue
            bot.photo(chat_id, path)
            for r in records:
                r['photo_sent'] = True
                r['prediction_receipt'] = {
                    'complete': True, 'transport': 'photo',
                    'group_key': kickoff_key(r), 'group_size': len(records),
                }
                r['final_sent'] = True
            save()
        except (TelegramError, OSError) as exc:
            ids = ','.join(str(r.get('match_id')) for r in records)
            print(f"Grup gönderimi bekliyor: {ids} / {safe_error(exc)}")

    for r in predictions.values():
        if excluded_record(r):
            continue
        try:
            deliver_record(r, bot, chat_id, save)
        except (TelegramError, OSError) as exc:
            print(f"Gönderim bekliyor: {r.get('match_id')} / {safe_error(exc)}")


def new_record(match, state, test_mode=False):
    kickoff = parse_utc(match['utcDate'])
    return {'schema_version': 3, 'season': str(match.get('season', {}).get('startDate', '2026'))[:4],
            'stage': match.get('stage'), 'matchday': match.get('matchday'), 'match_id': str(match['id']),
            'home_team': match['homeTeam']['name'], 'away_team': match['awayTeam']['name'],
            'home_crest': match.get('homeTeam', {}).get('crest'), 'away_crest': match.get('awayTeam', {}).get('crest'),
            'match_utc': kickoff.isoformat(), 'match_time': kickoff.astimezone(TURKEY).strftime('%d.%m.%Y %H:%M'),
            'created_at': utcnow(), 'score_scope': 'REGULAR_90', 'learning_policy': state['policy'],
            'policy_revision': state['revision'], 'ai_votes': [], 'pool_round': 0,
            'final_sent': False, 'result_sent': False, 'test_mode': test_mode}


def prepare_context(match, football):
    kickoff = parse_utc(match['utcDate'])
    context = {'season': match.get('season'), 'stage': match.get('stage'), 'matchday': match.get('matchday'),
               'match_utc': match['utcDate'], 'score_scope': 'REGULAR_90', 'home': {}, 'away': {}}
    for side in ('home', 'away'):
        team_id = match[side+'Team']['id']
        context[side]['team_id'] = team_id
        try:
            # Exclude not-yet-played fixtures and the current match from form.
            rows = football.get_team_matches(team_id, min(kickoff, now()))
            context[side]['last_5'] = enrich_team_context(build_team_form(rows, team_id), kickoff)
        except Exception as exc:
            context[side]['data_warning'] = safe_error(exc)
    try:
        standings = football.get_standings()
        table = {row['team']['id']: {k: row.get(k) for k in ('position', 'points', 'playedGames', 'goalsFor', 'goalsAgainst')}
                 for group in standings if group.get('type') == 'TOTAL' for row in group.get('table', [])}
        for side in ('home', 'away'):
            context[side]['standings'] = table.get(context[side]['team_id'])
    except Exception:
        pass
    return context


def prewarm_context(r, match, football, save):
    """Prepare factual data early without freezing XI, research or AI votes.

    This stage is explicitly token-free for AI providers. Partial API results
    can be retried by prepare_prediction nearer kickoff.
    """
    if excluded_fixture(match) or r.get('final_sent') or r.get('prediction_ready') or r.get('context_ready'):
        return False
    context = prepare_context(match, football)
    context['official_xi'] = (r.get('context') or {}).get('official_xi', {'status': 'NOT_ANNOUNCED'})
    r['context'] = context
    r['context_prepared_at'] = utcnow()
    r['context_ready'] = all('data_warning' not in context.get(side, {})
                             for side in ('home', 'away'))
    save()
    if r['context_ready']:
        print(f"PREFETCH | {r['match_id']} | structured context ready", flush=True)
    else:
        print(f"PREFETCH | {r['match_id']} | partial context; will retry", flush=True)
    return r['context_ready']


def research_gate_open(gate):
    if not gate or not gate.get('until'):
        return True
    try:
        return datetime.fromisoformat(gate['until'].replace('Z', '+00:00')) <= now()
    except (ValueError, TypeError):
        return True


def refresh_lineups(r, context, match, football, save, remaining):
    """Poll before T-30 without AI calls; retain every confirmed team XI."""
    existing = context.get('official_xi') or {'status': 'NOT_ANNOUNCED'}
    combined = merge_official_xi(existing, None)
    context['official_xi'] = combined
    if combined['status'] == 'ANNOUNCED':
        return combined

    # Persist a bounded poll interval across GitHub runs. A first T-30 check
    # is always allowed even if an earlier call occurred within four minutes.
    last = r.get('xi_checked_at')
    elapsed = None
    if last:
        try:
            elapsed = (now() - parse_utc(last)).total_seconds()
        except (ValueError, TypeError):
            pass
    crossed_deadline = remaining <= 30 and not r.get('xi_final_checked')
    if elapsed is None or elapsed >= 240 or crossed_deadline:
        r['xi_checked_at'] = now().isoformat()
        if remaining <= 30:
            r['xi_final_checked'] = True
        save()
        fetched = official_xi(football, match)
        combined = merge_official_xi(combined, fetched)
        context['official_xi'] = combined
        save()
    return combined


def lineup_availability(context):
    """Tell the models exactly which team has which quality of XI."""
    official = context.get('official_xi') or {}
    predicted = context.get('predicted_xi') or {}
    result = {}
    for side in ('home', 'away'):
        if valid_xi(official.get(side)):
            result[side] = 'OFFICIAL'
        elif valid_xi(predicted.get(side)):
            result[side] = 'PREDICTED'
        elif predicted.get(side):
            result[side] = 'INCOMPLETE_PREDICTED'
        else:
            result[side] = 'MISSING'
    return result


def prepare_prediction(r, match, football, predictions, state, save, deadline, test_mode=False,
                       research_gate=None, save_research_gate=None):
    """Resumable stages: lineup -> context -> research -> votes -> durable message."""
    if excluded_fixture(match):
        return False
    if r.get('prediction_ready'):
        return True
    remaining = minutes_left(match)
    if remaining <= 0:
        return False
    context = r.setdefault('context', {})
    if not r.get('inputs_frozen'):
        xi = refresh_lineups(r, context, match, football, save, remaining)
        # Wait for both confirmed starting XIs until T-30. If just one team
        # is confirmed, retain its XI and use probable-XI research for the other.
        if xi['status'] != 'ANNOUNCED' and remaining > 30 and not test_mode:
            return False
        # At T-30 use a source-labelled probable XI when official starters are
        # absent; this is a plain football-data lookup and consumes no AI tokens.
        if xi['status'] != 'ANNOUNCED' and not r.get('probable_xi_checked_at'):
            r['probable_xi_checked_at'] = utcnow()
            save()
            context['source_predicted_xi'] = source_predicted_xi(match) or {}
            save()
        if not r.get('context_ready'):
            xi = context['official_xi']
            prior_projection = context.get('source_predicted_xi') or {}
            context = prepare_context(match, football)
            context['official_xi'] = xi
            context['source_predicted_xi'] = prior_projection
            r['context'] = context
            r['context_ready'] = True
            save()
        if not r.get('research'):
            # Reserve a durable, source-labelled factual fallback BEFORE any
            # external AI call. A crash or quota error never fabricates news.
            fallback = structured_research(context, reason='RESEARCH_PENDING')
            r['research'] = fallback
            save()
            if (os.getenv('GEMINI_API_KEY') and time.monotonic() < deadline - 60
                    and research_gate_open(research_gate)):
                try:
                    from google import genai
                    client = genai.Client(api_key=os.environ['GEMINI_API_KEY'],
                        http_options={'timeout': 30000, 'retry_options': {'attempts': 1}})
                    actual = research_match(client, r['home_team'], r['away_team'], context)
                    if actual.get('status') == 'OK':
                        # A search summary is not authority to announce XIs;
                        # only the team-matched verified provider XI qualifies.
                        actual['official_xi'] = context['official_xi']
                        r['research'] = actual
                    else:
                        r['research_raw_unverified'] = {
                            'status': actual.get('status', 'UNKNOWN'),
                            'reason': 'UNVERIFIED_RESEARCH',
                        }
                        fallback['provider_warning'] = 'UNVERIFIED_RESEARCH'
                except Exception as exc:
                    reason = safe_error(exc)
                    r['research_raw_unverified'] = {'status': 'UNAVAILABLE', 'reason': reason}
                    fallback['provider_warning'] = reason
                    if reason in {'QUOTA_OR_RATE_LIMIT', 'PROVIDER_UNAVAILABLE'} and research_gate is not None:
                        # Avoid seven identical quota/503 searches in one batch
                        # and repeated searches every five minutes.
                        research_gate['until'] = (now() + timedelta(minutes=20)).isoformat()
                        research_gate['reason'] = reason
                        if save_research_gate:
                            save_research_gate()
            elif not research_gate_open(research_gate):
                fallback['provider_warning'] = 'PROVIDER_COOLDOWN'
            # Important: STRUCTURED_ONLY is NOT falsely marked as researched OK.
            print(f"RESEARCH | {r['match_id']} | {r['research'].get('status')} | "
                  f"{r['research'].get('provider_warning', 'OK')}", flush=True)
            context['predicted_xi'] = merge_predicted_xi(
                context.get('source_predicted_xi'), predicted_xi(r['research']),
                context.get('official_xi'),
            )
            # Keep the AI's research and context consistent about starter names.
            r['research']['predicted_xi'] = context['predicted_xi']
            # Never silently promote a short probable roster to a verified XI.
            context['lineup_availability'] = lineup_availability(context)
            print(f"XI | {r['match_id']} | home={context['lineup_availability']['home']} "
                  f"away={context['lineup_availability']['away']}", flush=True)
            r['history'] = learning_context(predictions, state, now())
            r['learning_policy'] = state['policy']
            r['policy_revision'] = state['revision']
            r['input_hash'] = digest({'context': context, 'research': r['research'], 'history': r['history']})
            r['inputs_frozen'] = True
            save()
    if not r.get('inputs_frozen'):
        # A process died after reserving research; resume without fabricating a completed call.
        context['predicted_xi'] = merge_predicted_xi(
            context.get('source_predicted_xi'), predicted_xi(r['research']),
            context.get('official_xi'),
        )
        r['research']['predicted_xi'] = context['predicted_xi']
        context['lineup_availability'] = lineup_availability(context)
        r['history'] = learning_context(predictions, state, now())
        r['input_hash'] = digest({'context': context, 'research': r['research'], 'history': r['history']})
        r['inputs_frozen'] = True
        save()
    if 'model_versions' not in r:
        import ai_pool
        r['model_versions'] = {key: getattr(ai_pool, key) for key in
            ('GEMINI_MODEL', 'MISTRAL_MODEL', 'GROQ_QWEN_MODEL', 'GROQ_120B_MODEL', 'COHERE_MODEL')}
        r['prompt_version'] = 4
        save()
    if minutes_left(match) <= 0:
        return False
    if r['pool_round'] == 0:
        r['pool_round'] = 1
        save()
    cached = {v['model']: {k: v.get(k) for k in ('model', 'success', 'result', 'error')} for v in r['ai_votes']}
    def on_vote(vote):
        r['ai_votes'] = [v for v in r['ai_votes'] if v['model'] != vote.model] + [asdict(vote)]
        save()
    votes = run_ai_pool(r['home_team'], r['away_team'], context, r['research'], r['history'],
                        cached=cached, on_vote=on_vote, deadline=deadline)
    # The pool retries each failed provider even when another model succeeds.
    # Do not start a second round that would bypass Retry-After or multiply calls.
    r['ai_votes'] = [asdict(v) for v in votes]
    if minutes_left(match) <= 0:
        r['late_generation'] = True
        save()
        return False
    r['consensus_min_successful'] = 3
    if any(v.success and v.result for v in votes):
        r['prediction_kind'] = 'AI'
        r['consensus'] = build_consensus(votes, min_successful=3)
    else:
        # Fifth approved format: publish no substitute prediction when no AI replies.
        r['prediction_kind'] = 'UNAVAILABLE'
        r['unavailable_details'] = [{'model': v.model, 'error': v.error} for v in votes]
        r['consensus'] = {'consensus_mode': 'NO_COMMON', 'winner_consensus': False, 'score_consensus': False}
    r['prediction_created_at'] = utcnow()
    r['minutes_before_match'] = round(minutes_left(match), 1)
    r['prediction_mode'] = r['consensus']['consensus_mode']
    r['published_consensus'] = copy.deepcopy(r['consensus'])
    r['message_format_version'] = FORMAT_VERSION
    r['prediction_table'] = prediction_tables(r)
    r['prediction_text'] = ('🧪 TEST\n' if test_mode else '') + prediction_message(r)
    r['prediction_ready'] = True
    r['image_required'] = True
    save()
    return True


def track_missed_fixtures(matches, predictions, state, bot, chat, save_state):
    """Never silently drop a known fixture if Actions missed the pre-match window."""
    tracked = state.setdefault('tracked_fixtures', {})
    for match in matches:
        if excluded_fixture(match):
            continue
        key = str(match['id'])
        kickoff = parse_utc(match['utcDate'])
        if kickoff > now():
            tracked[key] = {'utcDate': match['utcDate']}
        elif key in tracked and match.get('status') in {'IN_PLAY', 'PAUSED', 'FINISHED'}:
            record = predictions.get(key, {})
            if record.get('final_sent') or record.get('prediction_ready'):
                continue
            receipt = tracked[key].setdefault('missed_notice', {})
            if not receipt.get('complete'):
                text = (f"⚠️ {match['homeTeam']['name']} — {match['awayTeam']['name']}: "
                        "maç öncesi tahmin tamamlanamadı. Zamanlama/servis kayıtlarının incelenmesi gerekiyor.")
                tracked[key]['missed_text'] = text
                tracked[key]['missed_at'] = utcnow()
    save_state()


def main():
    test_mode = os.getenv('TEST_MODE', 'false').lower() == 'true'
    root = ROOT / 'test_runtime' if test_mode else ROOT
    predictions_path = root / 'match_predictions.json'
    state_path = root / 'data' / 'operations.json'
    cache_path = root / 'data' / 'provider_cache.json'
    predictions = load_json(predictions_path, {})
    state = load_json(state_path, new_state())
    if state.get('schema') != 1 or state.get('policy') not in POLICIES:
        raise StateError('Operasyon durum sürümü/politikası geçersiz; dosya korunuyor.')
    cache = load_json(cache_path, {})
    def save():
        save_json(predictions_path, predictions)
    def save_state():
        save_json(state_path, state)
    # Retain immutable migration input. Never silently rewrite the original evidence.
    backup = root / 'data' / 'pre_v3_predictions.json'
    if predictions and not backup.exists():
        save_json(backup, predictions)
    migrated = regrade_archived_results(predictions)
    if migrated:
        save()  # Persist once, even if a later external provider request fails.
        print(f"Kicktipp 8/6/4/0: {migrated} tarihi maç yeni standarda göre puanlandı.")
    apply_approved_policy(state, os.getenv('APPROVED_POLICY_FILE'))
    token, chat = os.getenv('TELEGRAM_BOT_TOKEN'), os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat:
        raise StateError('Tahmin botu TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secret eksik.')
    telegram = Telegram(token)
    drain_delivery(predictions, telegram, chat, save)
    football = CachedFootball(cache, lambda: save_json(cache_path, cache))
    matches = football.get_matches()
    track_missed_fixtures(matches, predictions, state, telegram, chat, save_state)
    refresh_results(predictions, matches)
    save()
    drain_delivery(predictions, telegram, chat, save)
    # Before the T-30 prediction window, build API-backed form and standings.
    # This uses no AI providers and helps seven simultaneous fixtures avoid
    # exhausting the final pre-kickoff processing budget.
    if not test_mode:
        upcoming = [m for m in matches if not excluded_fixture(m)
                    and m.get('status') in {'TIMED', 'SCHEDULED'}
                    and 0 < minutes_left(m) <= 90]
        upcoming.sort(key=lambda m: m['utcDate'])
        prewarm_end = time.monotonic() + 110  # leave the rest of this run free
        for match in upcoming:
            if time.monotonic() >= prewarm_end:
                break
            key = str(match['id'])
            r = predictions.setdefault(key, new_record(match, state, test_mode))
            if r.get('context_ready') or r.get('final_sent') or r.get('prediction_ready'):
                continue
            # Do not repeatedly call an unavailable API every five minutes.
            attempted_at = r.get('context_prefetch_attempt_at')
            if attempted_at:
                try:
                    last = parse_utc(attempted_at)
                    if (now() - last).total_seconds() < 900:
                        continue
                except (ValueError, TypeError):
                    pass
            r['context_prefetch_attempt_at'] = utcnow()
            save()
            try:
                prewarm_context(r, match, football, save)
            except Exception as exc:
                r['context_prefetch_error'] = safe_error(exc)
                save()

    candidates = [m for m in matches if not excluded_fixture(m)
                  and m.get('status') in {'TIMED', 'SCHEDULED'} and minutes_left(m) > 0
                  and (test_mode or minutes_left(m) <= 60)]
    candidates.sort(key=lambda m: m['utcDate'])
    if test_mode:
        candidates = candidates[:1]
    end = time.monotonic() + 600
    research_gate = {'until': state.get('research_backoff_until')}
    def save_gate():
        state['research_backoff_until'] = research_gate.get('until')
        state['research_backoff_reason'] = research_gate.get('reason')
        save_state()
    for match in candidates:
        if time.monotonic() >= end:
            break
        key = str(match['id'])
        r = predictions.setdefault(key, new_record(match, state, test_mode))
        if r.get('final_sent') or r.get('prediction_ready'):
            continue
        try:
            # Leave a safety margin to publish before kickoff, even after delayed Actions starts.
            deadline = min(end, time.monotonic() + max(0, minutes_left(match)*60 - 45))
            prepare_prediction(r, match, football, predictions, state, save, deadline, test_mode,
                               research_gate=research_gate, save_research_gate=save_gate)
        except StateError:
            raise
        except Exception as exc:
            r['last_processing_error'] = safe_error(exc)
            save()
            print(f'Maç işlemi bekliyor: {key} / {safe_error(exc)}')
    # Publish after all candidates are prepared so same-kickoff matches share one image.
    drain_delivery(predictions, telegram, chat, save)
    save()
    return 0
