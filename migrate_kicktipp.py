"""Explicit, OFFLINE Kicktipp 8/6/4/0 history migration.

Default: dry-run without writing ANY files.
To persist: python migrate_kicktipp.py --apply --confirm-kicktipp-8640
No imports or calls to network/AI/Telegram providers are made by this command.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from runner import ROOT, regrade_archived_results
from storage import StateError, load_json, save_json

# Only these derived fields may differ between the original and migrated record.
GRADE_FIELDS = frozenset({
    'grading_version', 'consensus_points', 'consensus_winner_applicable',
    'consensus_score_applicable', 'consensus_outcome_correct',
    'consensus_exact_score_correct', 'outcome_correct', 'exact_score_correct',
    'fallback_points', 'legacy_evaluation', 'pre_kicktipp_evaluation',
})
VOTE_GRADE_FIELDS = frozenset({'points', 'outcome_correct', 'exact_score_correct'})


def _immutable_projection(row):
    projection = copy.deepcopy(row)
    if not isinstance(projection, dict):
        return projection
    for key in GRADE_FIELDS:
        projection.pop(key, None)
    for vote in projection.get('ai_votes') or []:
        if isinstance(vote, dict):
            for key in VOTE_GRADE_FIELDS:
                vote.pop(key, None)
    return projection


def assert_archive_integrity(before, after):
    """Fail closed if ANY unapproved archival field changes."""
    if before.keys() != after.keys():
        raise StateError('Geçiş arşiv kayıtlarını ekledi veya sildi; kaydetme reddedildi.')
    for key, original in before.items():
        updated = after[key]
        if _immutable_projection(original) != _immutable_projection(updated):
            raise StateError(f'Korunan geçmiş tahmin veya FINAL alanı değişti: {key}')
        for name in ('legacy_evaluation', 'pre_kicktipp_evaluation'):
            if name in original and original[name] != updated.get(name):
                raise StateError(f'Mevcut tarihsel puan yedeği değişti: {key}/{name}')


def migrate_file(path: Path, apply: bool = False, confirmed: bool = False) -> tuple[int, Path | None]:
    """Read, migrate copy, validate and optionally back up + atomically persist."""
    if apply and not confirmed:
        raise StateError('Yazma için --apply ve --confirm-kicktipp-8640 birlikte gerekli.')
    path = Path(path)
    original_bytes = path.read_bytes()  # existing readable archive required; fail closed
    original = load_json(path, {})
    migrated = copy.deepcopy(original)
    count = regrade_archived_results(migrated)
    assert_archive_integrity(original, migrated)
    if not apply or not count:
        return count, None
    if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(original_bytes).digest():
        raise StateError('Arşiv inceleme sırasında değişti. Geçiş iptal edildi.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = path.with_name(f'{path.stem}.before_kicktipp_{stamp}{path.suffix}')
    # Preserve the EXACT source bytes before writing anything to the archive.
    with backup.open('xb') as handle:
        handle.write(original_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    save_json(path, migrated)
    if load_json(path, {}) != migrated:
        raise StateError(f'Geçiş sonrası arşiv doğrulaması başarısız; yedek: {backup}')
    return count, backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=ROOT / 'match_predictions.json')
    parser.add_argument('--apply', action='store_true', help='Apply offline migration to the archive')
    parser.add_argument('--confirm-kicktipp-8640', action='store_true', help='Explicit confirmation for --apply')
    args = parser.parse_args()
    count, backup = migrate_file(args.archive, args.apply, args.confirm_kicktipp_8640)
    if backup:
        print(f'Kicktipp 8/6/4/0: {count} kayıt kontrollü güncellendi. Orijinal yedek: {backup}')
    else:
        print(f'Kicktipp 8/6/4/0: {count} kayıt kontrol edildi. ' +
              ('Güncellemeye gerek yok.' if args.apply else 'ÖN İZLEME; hiçbir dosya değiştirilmedi.'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
