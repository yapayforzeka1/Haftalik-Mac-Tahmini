"""Read-only evaluation of archived UCL model votes and published consensus.

Usage: python performance_analysis.py [path/to/match_predictions.json]
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from scoring import VERSION, score_prediction, outcome_points


def parse_score(value):
    if not isinstance(value, str):
        return None
    parts = value.strip().split('-')
    if len(parts) != 2 or any(not x.strip().isdigit() for x in parts):
        return None
    return tuple(map(int, parts))


def outcome(score):
    return 'HOME' if score[0] > score[1] else 'AWAY' if score[0] < score[1] else 'DRAW'


def evaluate(records):
    stats = defaultdict(lambda: {'eligible': 0, 'outcome_correct': 0, 'exact_correct': 0, 'missing': 0, 'goal_difference_correct': 0, 'points': 0})
    total = 0
    for match in records.values() if isinstance(records, dict) else records:
        if not isinstance(match, dict):
            continue
        actual = match.get('actual') or {}
        if actual.get('status') != 'FINISHED' or actual.get('scope') != 'REGULAR_90':
            continue
        h, a = actual.get('home'), actual.get('away')
        if type(h) is not int or type(a) is not int or min(h, a) < 0:
            continue
        total += 1
        truth = (h, a)
        entries = [('Ortak karar', match.get('published_consensus') or match.get('consensus') or {})]
        entries.extend((str(v.get('model') or 'Bilinmeyen model'), v.get('result') if v.get('success') else {}) for v in match.get('ai_votes', []) if isinstance(v, dict))
        for name, prediction in entries:
            row = stats[name]
            if not isinstance(prediction, dict):
                row['missing'] += 1
                continue
            score = parse_score(prediction.get('score'))
            direction = prediction.get('outcome')
            if direction not in ('HOME', 'AWAY', 'DRAW') and score is not None:
                direction = outcome(score)
            if direction not in ('HOME', 'AWAY', 'DRAW') or (score is None and name != 'Ortak karar'):
                row['missing'] += 1
                continue
            row['eligible'] += 1
            row['outcome_correct'] += int(direction == outcome(truth))
            row['exact_correct'] += int(score == truth)
            if score is not None:
                row['points'] += score_prediction(prediction['score'], h, a)
                row['goal_difference_correct'] += int(score[0] - score[1] == h - a)
            elif name == 'Ortak karar':
                # Correct outcome without published common score earns at most 4.
                row['points'] += outcome_points(direction, outcome(truth))
    return total, dict(sorted(stats.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', nargs='?', type=Path, default=Path(__file__).with_name('match_predictions.json'))
    args = parser.parse_args()
    with args.archive.open(encoding='utf-8') as f:
        records = json.load(f)
    total, stats = evaluate(records)
    print(f'90 dakika sonucu arşivde doğrulanmış maç: {total}')
    print(f'Puanlama standardı: {VERSION}')
    print(f'{"Model":<27} {"Geçerli":>7} {"Eksik":>6} {"1-X-2":>13} {"Doğru skor":>15} {"Gol farkı":>12} {"Puan":>7} {"Ortalama":>9}')
    for name, row in stats.items():
        n = row['eligible']
        fmt = lambda count: f'{count}/{n} (%{100*count/n:.1f})' if n else 'Veri yok'
        avg = f'{row["points"] / n:.2f}' if n else '—'
        print(f'{name[:27]:<27} {n:>7} {row["missing"]:>6} {fmt(row["outcome_correct"]):>13} {fmt(row["exact_correct"]):>15} {row["goal_difference_correct"]:>12} {row["points"]:>7} {avg:>9}')
    print('Not: Geçerli tahmini olmayan maçlar başarısız tahmin olarak sayılmaz; kapsam dışında raporlanır.')
    print('Not: Tahminlerin maç başlamadan önce üretildiği bu analizde ayrıca doğrulanmaz.')


if __name__ == '__main__':
    main()
