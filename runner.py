from __future__ import annotations

import copy
import os
import subprocess
import time
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ai_pool import run_ai_pool, safe_error
from gemini_budget import GeminiRequestBudget
from consensus_engine import build_consensus
from experimental_scores import freeze_prospective_experiments
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
from telegram_io import Telegram, TelegramDeliveryUncertain, TelegramError, deliver_text
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
        if previous:
            if unchanged:
                # Historical scoring versions are migrated ONLY by the explicit
                # offline migration command, never during regular prediction runs.
                continue
            # Provider revisions must not alter previously published FINAL
            # messages, delivery receipts or archived 90-minute evaluations.
            # Record a proposed correction for manual review instead.
            proposed = copy.deepcopy(actual)
            pending = r.get('result_correction_pending_review')
            if not isinstance(pending, dict) or pending.get('proposed_actual') != proposed:
                r['result_correction_pending_review'] = {
                    'proposed_actual': proposed,
                    'observed_at': utcnow(),
                    'reason': 'Official result differs from stored result; manual review required.',
                }
            continue
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
        if r.get('prediction_kind', 'AI') == 'AI':
            grade_record(r)
            # Past analysis is an historical artifact; do not regenerate it.
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


PHOTO_RETRY_BASE_SECONDS = 300
PHOTO_RETRY_MAX_SECONDS = 900
PHOTO_MAX_ATTEMPTS = 3


def _photo_delivery_state(record):
    state = record.get('photo_delivery')
    return state if isinstance(state, dict) else {}


def _photo_attempt_count(state):
    try:
        return max(0, int(state.get('attempt_count', 0)))
    except (TypeError, ValueError):
        return 0


def _photo_retry_delay(attempt_count):
    exponent = max(0, int(attempt_count) - 1)
    return min(PHOTO_RETRY_BASE_SECONDS * (2 ** exponent), PHOTO_RETRY_MAX_SECONDS)


def _photo_retry_after(state):
    value = state.get('retry_after_at')
    if value:
        try:
            return parse_utc(value)
        except (ValueError, TypeError):
            pass
    attempted = state.get('attempted_at') or state.get('finished_at')
    if attempted:
        try:
            return parse_utc(attempted) + timedelta(seconds=_photo_retry_delay(max(1, _photo_attempt_count(state))))
        except (ValueError, TypeError):
            pass
    return None


def _photo_retry_due(state, clock=None):
    clock = clock or now
    retry_after = _photo_retry_after(state)
    # Legacy records without timestamps are made retryable instead of being
    # permanently blocked; the current run still observes the retry limit.
    return retry_after is None or clock() >= retry_after


def _mark_photo_attempt(records, mode, **details):
    for record in records:
        previous = _photo_delivery_state(record)
        attempts = _photo_attempt_count(previous) + 1
        first_attempt = previous.get('first_attempt_at') or previous.get('attempted_at') or utcnow()
        state = {
            'status': 'SENDING', 'mode': mode, 'attempted_at': utcnow(),
            'first_attempt_at': first_attempt, 'attempt_count': attempts,
        }
        state.update(details)
        record['photo_delivery'] = state


def _mark_photo_failure(records, status, exc, clock=None):
    for record in records:
        state = record.setdefault('photo_delivery', {})
        state['status'] = status
        state['error'] = safe_error(exc)
        state['finished_at'] = utcnow()
        if status in {'UNCERTAIN', 'REJECTED'}:
            retry_clock = clock or now
            delay = 0 if status == 'REJECTED' else _photo_retry_delay(max(1, _photo_attempt_count(state)))
            state['retry_after_at'] = (retry_clock() + timedelta(seconds=delay)).isoformat()


def _checkpoint_photo_attempt(records, mode, save, checkpoint=None, **details):
    """Persist SENDING before the external request when running in Actions."""
    previous = [copy.deepcopy(record.get('photo_delivery')) for record in records]
    _mark_photo_attempt(records, mode, **details)
    save()
    if checkpoint is None:
        return
    try:
        checkpoint()
    except Exception as exc:
        # No Telegram request has been made. Restore the prior local state so
        # the workflow's final save cannot accidentally publish a false SENDING.
        for record, old_state in zip(records, previous):
            if old_state is None:
                record.pop('photo_delivery', None)
            else:
                record['photo_delivery'] = old_state
        save()
        raise StateError(
            'Gönderim öncesi teslimat kaydı GitHub üzerinde kalıcılaştırılamadı; Telegram isteği gönderilmedi.'
        ) from exc


def _persist_delivery_checkpoint(path):
    """Commit and push the pre-send marker before Telegram can accept a photo.

    Stage the same runtime state files as the workflow's final commit. Other
    runtime files may already be modified at this point, and leaving them
    unstaged can make git pull --rebase refuse to run. Outside Actions this is
    intentionally a no-op, so local tests never touch Git.
    """
    if os.getenv('GITHUB_ACTIONS', '').lower() != 'true':
        return
    if os.getenv('TEST_MODE', 'false').lower() == 'true':
        return
    if not (ROOT / '.git').exists():
        raise StateError('Gönderim öncesi kalıcı kayıt için Git çalışma alanı bulunamadı.')
    try:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise StateError('Teslimat arşivi depo kökünün dışında.') from exc

    def run_git(args, *, check=True):
        return subprocess.run(
            ['git', *args], cwd=ROOT, check=check, capture_output=True, text=True,
            timeout=60,
        )

    state_paths = [relative]
    for candidate in ('match_predictions.json', 'data/operations.json',
                      'data/provider_cache.json', 'data/pre_v3_predictions.json',
                      'data/gemini_usage.json'):
        if (ROOT / candidate).is_file():
            state_paths.append(candidate)
    state_paths = sorted(set(state_paths))
    try:
        run_git(['add', '--', *state_paths])
        staged = run_git(['diff', '--cached', '--quiet'], check=False)
        if staged.returncode == 0:
            return
        if staged.returncode != 1:
            raise StateError('Git teslimat kaydı değişiklikleri doğrulanamadı.')
        run_git(['config', 'user.name', 'github-actions[bot]'])
        run_git(['config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'])
        run_git(['commit', '-m', 'Checkpoint Telegram delivery attempt'])
        branch = os.getenv('GITHUB_REF_NAME') or 'main'
        run_git(['pull', '--rebase', 'origin', branch])
        run_git(['push', 'origin', f'HEAD:refs/heads/{branch}'])
    except (subprocess.SubprocessError, OSError) as exc:
        # A conflicted 'git pull --rebase' leaves .git/rebase-merge behind, which makes
        # every later git command in this job fail. Always clean it up before giving up.
        try:
            subprocess.run(['git', 'rebase', '--abort'], cwd=ROOT, check=False,
                           capture_output=True, text=True, timeout=60)
        except (subprocess.SubprocessError, OSError):
            pass
        raise StateError('Gönderim öncesi teslimat kaydı GitHub üzerinde kalıcılaştırılamadı.') from exc


def _mark_needs_review(record, reason):
    state = record.setdefault('photo_delivery', {})
    if state.get('status') != 'NEEDS_REVIEW':
        state['needs_review_at'] = utcnow()
        print(f"DELIVERY_NEEDS_REVIEW | {record.get('match_id')} | {reason}", flush=True)
    state['status'] = 'NEEDS_REVIEW'
    state['error'] = reason


def _photo_is_blocked(record, clock=None):
    state = _photo_delivery_state(record)
    status = state.get('status')
    if status in {'SENDING', 'NEEDS_REVIEW', 'SENT'}:
        return True
    attempts = _photo_attempt_count(state)
    if status == 'UNCERTAIN':
        # Group retries are only performed by drain_delivery, preserving the
        # original group boundary and never falling back to individual photos.
        return state.get('mode') == 'group' or not _photo_retry_due(state, clock) or attempts >= PHOTO_MAX_ATTEMPTS
    if status == 'REJECTED' and state.get('mode') == 'single':
        return not _photo_retry_due(state, clock) or attempts >= PHOTO_MAX_ATTEMPTS
    return False


def deliver_record(r, bot, chat_id, save, clock=None, checkpoint=None):
    """Resume a single prediction without regenerating or blindly duplicating it."""
    if not r.get('prediction_ready') or r.get('final_sent'):
        return
    clock = clock or now
    kickoff = parse_utc(r['match_utc'])
    if r.get('message_format_version', 0) >= FORMAT_VERSION:
        photo_state = _photo_delivery_state(r)
        if photo_state.get('status') == 'SENT':
            r['photo_sent'] = True
            r['prediction_receipt'] = {
                'complete': True, 'transport': 'photo',
                'group_key': photo_state.get('group_key'),
                'group_size': photo_state.get('group_size', 1),
            }
            r['final_sent'] = True
            save()
            return
        if _photo_is_blocked(r, clock):
            if (_photo_delivery_state(r).get('status') in {'UNCERTAIN', 'REJECTED'}
                    and _photo_attempt_count(_photo_delivery_state(r)) >= PHOTO_MAX_ATTEMPTS):
                _mark_needs_review(r, 'Gönderim deneme sınırına ulaştı; manuel kontrol gerekiyor.')
                save()
            return
        if r.get('photo_sent') or r.get('prediction_receipt', {}).get('complete'):
            r['final_sent'] = True
            save()
            return
        if clock() < kickoff:
            from match_report import render_match_group_image
            path = render_match_group_image([r], test_mode=bool(r.get('test_mode')))
            if clock() < kickoff:
                _checkpoint_photo_attempt([r], 'single', save, checkpoint,
                                          group_key=None, group_size=1)
                try:
                    bot.photo(chat_id, path)
                except TelegramDeliveryUncertain as exc:
                    _mark_photo_failure([r], 'UNCERTAIN', exc, clock=clock)
                    save()
                    raise
                except (TelegramError, OSError) as exc:
                    _mark_photo_failure([r], 'REJECTED', exc, clock=clock)
                    save()
                    raise
                state = r['photo_delivery']
                state['status'] = 'SENT'
                state['finished_at'] = utcnow()
                r['photo_sent'] = True
                r['prediction_receipt'] = {
                    'complete': True, 'transport': 'photo',
                    'group_key': None, 'group_size': 1,
                }
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
        photo_state = _photo_delivery_state(r)
        if _photo_is_blocked(r, clock):
            if (_photo_delivery_state(r).get('status') in {'UNCERTAIN', 'REJECTED'}
                    and _photo_attempt_count(_photo_delivery_state(r)) >= PHOTO_MAX_ATTEMPTS):
                _mark_needs_review(r, 'Gönderim deneme sınırına ulaştı; manuel kontrol gerekiyor.')
                save()
            return
        if photo_state.get('status') == 'SENT':
            r['photo_sent'] = True
        elif clock() >= kickoff:
            r['photo_skipped_after_kickoff'] = True
        else:
            from match_report import render_match_group_image
            path = render_match_group_image([r], test_mode=bool(r.get('test_mode')))
            _checkpoint_photo_attempt([r], 'single', save, checkpoint,
                                      group_key=None, group_size=1)
            try:
                bot.photo(chat_id, path)
            except TelegramDeliveryUncertain as exc:
                _mark_photo_failure([r], 'UNCERTAIN', exc, clock=clock)
                save()
                raise
            except (TelegramError, OSError) as exc:
                _mark_photo_failure([r], 'REJECTED', exc, clock=clock)
                save()
                raise
            r['photo_delivery']['status'] = 'SENT'
            r['photo_delivery']['finished_at'] = utcnow()
            r['photo_sent'] = True
            save()
    r['final_sent'] = True
    save()


def drain_delivery(predictions, bot, chat_id, save, checkpoint=None):
    """Send by kickoff group, retrying uncertain delivery only in a bounded way."""
    from collections import defaultdict
    from match_report import kickoff_key, render_match_group_image

    recovered = False
    current_time = now()
    for r in predictions.values():
        state = _photo_delivery_state(r)
        status = state.get('status')
        if status == 'SENDING':
            state['status'] = 'UNCERTAIN'
            state['error'] = 'Önceki çalıştırma gönderim sonucu alınmadan sonlandı.'
            state['finished_at'] = utcnow()
            state['attempt_count'] = max(1, _photo_attempt_count(state))
            retry_after = _photo_retry_after(state)
            state['retry_after_at'] = (retry_after or (current_time + timedelta(seconds=PHOTO_RETRY_BASE_SECONDS))).isoformat()
            recovered = True
        elif status == 'UNCERTAIN' and not state.get('retry_after_at'):
            retry_after = _photo_retry_after(state)
            state['retry_after_at'] = (retry_after or (current_time + timedelta(seconds=PHOTO_RETRY_BASE_SECONDS))).isoformat()
            recovered = True
        if state.get('status') in {'UNCERTAIN', 'REJECTED'} and _photo_attempt_count(state) >= PHOTO_MAX_ATTEMPTS:
            _mark_needs_review(r, 'Gönderim deneme sınırına ulaştı; manuel kontrol gerekiyor.')
            recovered = True
        elif state.get('status') == 'SENT' and not r.get('final_sent'):
            r['photo_sent'] = True
            r['prediction_receipt'] = {
                'complete': True, 'transport': 'photo',
                'group_key': state.get('group_key'),
                'group_size': state.get('group_size', 1),
            }
            r['final_sent'] = True
            recovered = True
    if recovered:
        save()

    groups = defaultdict(list)
    for r in predictions.values():
        if excluded_record(r) or r.get('final_sent'):
            continue
        state = _photo_delivery_state(r)
        status = state.get('status')
        if status in {'SENDING', 'SENT', 'NEEDS_REVIEW'}:
            continue
        if status == 'UNCERTAIN':
            if (not _photo_retry_due(state) or _photo_attempt_count(state) >= PHOTO_MAX_ATTEMPTS
                    or state.get('mode') != 'group' or not state.get('group_key')):
                continue
            # Retry only the exact set of records from the original group.
            group_identity = ('retry', str(state['group_key']), bool(r.get('test_mode')))
        elif status == 'REJECTED' and state.get('mode') == 'single':
            continue  # deliver_record applies the same retry delay to single sends.
        else:
            try:
                if not (r.get('prediction_ready')
                        and r.get('message_format_version', 0) >= FORMAT_VERSION
                        and not r.get('photo_sent')
                        and not r.get('prediction_receipt', {}).get('complete')
                        and now() < parse_utc(r['match_utc'])):
                    continue
                group_identity = ('new', kickoff_key(r), bool(r.get('test_mode')))
            except (KeyError, ValueError):
                continue
        if not r.get('prediction_ready') or r.get('photo_sent') or r.get('prediction_receipt', {}).get('complete'):
            continue
        try:
            if now() < parse_utc(r['match_utc']):
                groups[group_identity].append(r)
        except (KeyError, ValueError):
            continue

    for (group_mode, group_id, is_test), records in sorted(groups.items()):
        ids = ','.join(str(r.get('match_id')) for r in records)
        try:
            kickoff = min(parse_utc(r['match_utc']) for r in records)
            if now() >= kickoff:
                continue
            path = render_match_group_image(records, test_mode=is_test)
            if now() >= kickoff:
                continue
        except OSError as exc:
            print(f"Grup görseli hazırlanamadı; tekli gönderim denenecek: {ids} / {safe_error(exc)}")
            continue

        if group_mode == 'retry':
            original_key = group_id
        else:
            original_key = group_id
        try:
            _checkpoint_photo_attempt(records, 'group', save, checkpoint,
                                      group_key=original_key, group_size=len(records))
        except StateError as exc:
            print(f"Gönderim öncesi kayıt başarısız; mesaj gönderilmedi: {ids} / {safe_error(exc)}", flush=True)
            raise
        try:
            bot.photo(chat_id, path)
        except TelegramDeliveryUncertain as exc:
            _mark_photo_failure(records, 'UNCERTAIN', exc)
            save()
            print(f"Grup gönderimi belirsiz; kontrollü tekrar planlandı: {ids} / {safe_error(exc)}")
        except (TelegramError, OSError) as exc:
            _mark_photo_failure(records, 'REJECTED', exc)
            save()
            print(f"Grup gönderimi reddedildi; tekli gönderim denenecek: {ids} / {safe_error(exc)}")
        else:
            for r in records:
                state = r['photo_delivery']
                state['status'] = 'SENT'
                state['finished_at'] = utcnow()
                r['photo_sent'] = True
                r['prediction_receipt'] = {
                    'complete': True, 'transport': 'photo',
                    'group_key': original_key, 'group_size': len(records),
                }
                r['final_sent'] = True
            save()

    for r in predictions.values():
        if excluded_record(r):
            continue
        try:
            deliver_record(r, bot, chat_id, save, checkpoint=checkpoint)
        except (TelegramError, OSError) as exc:
            print(f"Gönderim bekliyor: {r.get('match_id')} / {safe_error(exc)}")

    # Exhausted retries must not silently disappear; send one consolidated alert.
    needs_review = [
        r for r in predictions.values()
        if not excluded_record(r) and not r.get('final_sent')
        and _photo_delivery_state(r).get('status') == 'NEEDS_REVIEW'
        and not (_photo_delivery_state(r).get('review_notice') or {}).get('complete')
        and not (_photo_delivery_state(r).get('review_notice') or {}).get('uncertain')
    ]
    if needs_review:
        lines = [f"• {r.get('home_team', '?')} — {r.get('away_team', '?')} (ID {r.get('match_id', '?')})"
                 for r in needs_review]
        text = ('⚠️ Telegram teslimatı doğrulanamadı. Otomatik deneme sınırına ulaşıldı; '
                'aşağıdaki tahminler için kayıt kontrolü gerekiyor:\n' + '\n'.join(lines))
        receipt = _photo_delivery_state(needs_review[0]).setdefault('review_notice', {})
        for r in needs_review:
            _photo_delivery_state(r)['review_notice'] = receipt
        try:
            deliver_text(bot, chat_id, text, receipt, save)
        except (TelegramError, OSError) as exc:
            save()
            print(f"Teslimat kontrol bildirimi gönderilemedi: {safe_error(exc)}", flush=True)

def _successful_ai_count(votes):
    return sum(1 for v in votes if v.get('success') and isinstance(v.get('result'), dict))


def _votes_complete(votes):
    """Exactly five distinct, valid provider votes are required for completion."""
    by_model = {v.get('model'): v for v in votes if v.get('model')}
    return (len(by_model) == 5 and all(v.get('success') and isinstance(v.get('result'), dict)
                                       for v in by_model.values()))


def _vote_signature(votes):
    return sorted((v.get('model'), bool(v.get('success')), v.get('result'), v.get('error'),
                   v.get('retry_after'), v.get('error_stage'), v.get('http_status')) for v in votes)


def drain_prediction_updates(predictions, bot, chat_id, save):
    """Send resumable text updates when a previously delivered partial forecast gains votes."""
    for record in predictions.values():
        if not record.get('prediction_update_required') or not record.get('final_sent'):
            continue
        receipt = record.setdefault('prediction_update_receipt', {})
        count = _successful_ai_count(record.get('ai_votes') or [])
        complete = bool(record.get('prediction_complete'))
        label = 'Nihai tahmin tamamlandı (5/5 AL)' if complete else f'Tahmin güncellendi ({count}/5 AL başarılı; kısmi)'
        text = f"🔄 {label}\n{record.get('home_team', '—')} — {record.get('away_team', '—')}\n\n{record.get('prediction_text', '')}"
        try:
            deliver_text(bot, chat_id, text, receipt, save)
        except (TelegramError, OSError) as exc:
            print(f"Tahmin güncellemesi bekliyor: {record.get('match_id')} / {safe_error(exc)}")
            continue
        if receipt.get('complete'):
            record['prediction_update_required'] = False
            record['published_successful_ai'] = count
            record['published_prediction_complete'] = complete
            record['prediction_update_sent_at'] = utcnow()
            save()


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
                       research_gate=None, save_research_gate=None, gemini_budget=None):
    """Resumable stages: lineup -> context -> research -> votes -> durable message."""
    if excluded_fixture(match):
        return False
    if r.get('prediction_ready') and _votes_complete(r.get('ai_votes') or []):
        if r.get('prediction_complete') is not True:
            r['prediction_complete'] = True
            r['consensus_status'] = 'FINAL'
            r['prediction_table'] = prediction_tables(r)
            r['prediction_text'] = ('🧪 TEST\n' if r.get('test_mode') else '') + prediction_message(r)
            if r.get('final_sent') and not r.get('published_prediction_complete'):
                r['prediction_update_required'] = True
                r['prediction_update_receipt'] = {}
            save()
        return True
    if r.get('prediction_ready') and r.get('prediction_complete') is True:
        return True
    previous_ready = bool(r.get('prediction_ready'))
    previous_complete = bool(r.get('prediction_complete') or _votes_complete(r.get('ai_votes') or []))
    previous_votes = copy.deepcopy(r.get('ai_votes') or [])
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
            # Gemini's limited quota is reserved for the five-model match forecast.
            # Research stays explicitly source-backed and never calls an AI API.
            r['research']['provider_warning'] = 'STRUCTURED_RESEARCH_ONLY'
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
    cached = {v['model']: {k: v.get(k) for k in
              ('model', 'success', 'result', 'error', 'retry_after', 'error_stage', 'http_status', 'error_detail',
               'request_attempts', 'elapsed_seconds', 'queue_wait_seconds')}
              for v in r['ai_votes']}
    def on_vote(vote):
        r['ai_votes'] = [v for v in r['ai_votes'] if v['model'] != vote.model] + [asdict(vote)]
        save()
    votes = run_ai_pool(r['home_team'], r['away_team'], context, r['research'], r['history'],
                        cached=cached, on_vote=on_vote, deadline=deadline,
                        gemini_budget=gemini_budget)
    # The pool retries each failed provider even when another model succeeds.
    # Do not start a second round that would bypass Retry-After or multiply calls.
    r['ai_votes'] = [asdict(v) for v in votes]
    r['total_ai'] = len(votes)
    complete = _votes_complete(r['ai_votes'])
    successful_count = _successful_ai_count(r['ai_votes'])
    if previous_ready and _vote_signature(previous_votes) == _vote_signature(r['ai_votes']):
        r['prediction_complete'] = complete
        save()
        return True
    published_count = int(r.get('published_successful_ai', _successful_ai_count(previous_votes)))
    published_complete = bool(r.get('published_prediction_complete', previous_complete))
    if r.get('final_sent') and (successful_count > published_count or (complete and not published_complete)):
        if not r.get('prediction_update_required'):
            r['prediction_update_receipt'] = {}
        r['prediction_update_required'] = True
    r['prediction_complete'] = complete
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
    if not previous_ready:
        r['prediction_created_at'] = utcnow()
        # One-way, pre-kickoff archive metadata is frozen only on first publication.
        freeze_prospective_experiments(r, created_at=r['prediction_created_at'])
        r['minutes_before_match'] = round(minutes_left(match), 1)
    r['prediction_mode'] = r['consensus']['consensus_mode']
    r['published_consensus'] = copy.deepcopy(r['consensus'])
    r['message_format_version'] = FORMAT_VERSION
    r['prediction_table'] = prediction_tables(r)
    r['prediction_text'] = ('🧪 TEST\n' if test_mode else '') + prediction_message(r)
    r['prediction_ready'] = True
    r['prediction_complete'] = complete
    r['consensus_status'] = 'FINAL' if complete else 'PROVISIONAL'
    r['image_required'] = True
    save()
    return True


def track_missed_fixtures(matches, predictions, state, bot, chat, save_state):
    """Persist and send a notice when a known fixture has no confirmed delivery."""
    tracked = state.setdefault('tracked_fixtures', {})
    for match in matches:
        if excluded_fixture(match):
            continue
        key = str(match['id'])
        kickoff = parse_utc(match['utcDate'])
        if kickoff > now():
            tracked.setdefault(key, {'utcDate': match['utcDate']})
            continue
        if match.get('status') not in {'IN_PLAY', 'PAUSED', 'FINISHED'}:
            continue
        record = predictions.get(key, {})
        if record.get('final_sent'):
            continue
        if (_photo_delivery_state(record).get('review_notice') or {}).get('complete'):
            continue
        notice = tracked.setdefault(key, {'utcDate': match['utcDate']}).setdefault('missed_notice', {})
        if notice.get('complete') or notice.get('uncertain'):
            continue
        if record.get('prediction_ready'):
            text = (f"⚠️ {match['homeTeam']['name']} — {match['awayTeam']['name']}: "
                    "tahmin oluşturuldu ancak Telegram teslimatı doğrulanamadı. "
                    "Gönderim kaydının manuel kontrol edilmesi gerekiyor.")
        else:
            text = (f"⚠️ {match['homeTeam']['name']} — {match['awayTeam']['name']}: "
                    "maç öncesi tahmin tamamlanamadı. Zamanlama/servis kayıtlarının incelenmesi gerekiyor.")
        tracked[key]['missed_text'] = text
        tracked[key]['missed_at'] = tracked[key].get('missed_at') or utcnow()
        try:
            deliver_text(bot, chat, text, notice, save_state)
        except (TelegramError, OSError) as exc:
            tracked[key]['missed_notice_error'] = safe_error(exc)
            save_state()
            print(f"Eksik tahmin bildirimi bekliyor: {key} / {safe_error(exc)}", flush=True)
    save_state()


def main():
    test_mode = os.getenv('TEST_MODE', 'false').lower() == 'true'
    # TEST requests consume the same Google project quota, so the ledger is
    # shared with production while prediction archives remain isolated.
    from ai_pool import GEMINI_MODEL
    gemini_budget = GeminiRequestBudget(
        ROOT / 'data' / 'gemini_usage.json', GEMINI_MODEL,
        rpm=int(os.getenv('GEMINI_REQUESTS_PER_MINUTE', '5')),
        rpd=int(os.getenv('GEMINI_REQUESTS_PER_DAY', '20')),
    )
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
    def checkpoint_delivery():
        save()
        _persist_delivery_checkpoint(predictions_path)
    apply_approved_policy(state, os.getenv('APPROVED_POLICY_FILE'))
    token, chat = os.getenv('TELEGRAM_BOT_TOKEN'), os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat:
        raise StateError('Tahmin botu TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secret eksik.')
    telegram = Telegram(token)
    drain_delivery(predictions, telegram, chat, save, checkpoint=checkpoint_delivery)
    drain_prediction_updates(predictions, telegram, chat, save)
    football = CachedFootball(cache, lambda: save_json(cache_path, cache))
    matches = football.get_matches()
    # The isolated test archive has no production delivery receipts. Checking
    # historical fixtures against it would send false missed-match notices.
    if not test_mode:
        track_missed_fixtures(matches, predictions, state, telegram, chat, save_state)
    refresh_results(predictions, matches)
    save()
    drain_delivery(predictions, telegram, chat, save, checkpoint=checkpoint_delivery)
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
        if r.get('prediction_complete') is True or (r.get('prediction_ready') and _votes_complete(r.get('ai_votes') or [])):
            continue
        try:
            # Leave a safety margin to publish before kickoff, even after delayed Actions starts.
            deadline = min(end, time.monotonic() + max(0, minutes_left(match)*60 - 45))
            prepare_prediction(r, match, football, predictions, state, save, deadline, test_mode,
                               research_gate=research_gate, save_research_gate=save_gate,
                               gemini_budget=gemini_budget)
        except StateError:
            raise
        except Exception as exc:
            r['last_processing_error'] = safe_error(exc)
            save()
            print(f'Maç işlemi bekliyor: {key} / {safe_error(exc)}')
    # Publish after all candidates are prepared so same-kickoff matches share one image.
    drain_delivery(predictions, telegram, chat, save, checkpoint=checkpoint_delivery)
    drain_prediction_updates(predictions, telegram, chat, save)
    save()
    return 0
