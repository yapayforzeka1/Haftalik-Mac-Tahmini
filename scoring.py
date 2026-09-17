"""User-approved, stage-independent scoring; regulation time includes stoppage time."""
import re

VERSION = "3:6-5-3-2-0:REGULAR"


def outcome(home, away):
    return "HOME" if home > away else "AWAY" if home < away else "DRAW"


def parse_score(value):
    match = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", str(value or ""))
    return tuple(map(int, match.groups())) if match else None


def score_prediction(score, home, away):
    predicted = parse_score(score)
    if predicted is None:
        return 0
    ph, pa = predicted
    if predicted == (home, away):
        return 6
    if outcome(ph, pa) != outcome(home, away):
        return 0
    if home == away:
        return 3
    return 5 if ph - pa == home - away else 2


def outcome_points(predicted, actual):
    return (3 if actual == "DRAW" else 2) if predicted == actual else 0


def regulation_score(match):
    """Never grade extra-time/shootout fullTime as a 90-minute result."""
    score = match.get("score") or {}
    duration = score.get("duration")
    values = score.get("regularTime")
    if (not isinstance(values, dict) or values.get('home') is None or values.get('away') is None) and duration == "REGULAR":
        values = score.get("fullTime")
    if not isinstance(values, dict):
        return None
    home, away = values.get("home"), values.get("away")
    if type(home) is not int or type(away) is not int or min(home, away) < 0:
        return None
    return home, away
