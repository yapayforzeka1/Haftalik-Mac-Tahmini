"""Approved Champions League prediction visuals for Telegram.

Single-match and same-kickoff multi-match predictions share one visual language.
Every match card shows the archived AI votes, consensus, confidence, a short
analysis derived from the model reasons, and only data that is actually present.
"""
from __future__ import annotations

import hashlib
import io
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from messages import kickoff_text, label, prediction_tables, short_model, short_reason

REPORT_DIR = Path("reports")
WIDTH = 1480
PAD = 34
BG = "#07111f"
PANEL = "#0d1b2d"
CARD = "#11243a"
CARD_2 = "#0a1727"
BORDER = "#24405e"
TEXT = "#f3f7fb"
MUTED = "#9bb0c6"
BLUE = "#27a7ff"
BLUE_DIM = "#123b5b"
GOLD = "#d7b45a"
GREEN = "#35d07f"
WARN = "#f5b942"
RED = "#ef6a6a"
WHITE = "#ffffff"

TEAM_COLORS = {
    "galatasaray": "#a90432", "fenerbahce": "#00205b", "besiktas": "#1a1a1a",
    "trabzonspor": "#6a1b1b", "sporting": "#0a7a3e", "benfica": "#e30613",
    "inter": "#0166b1", "porto": "#003399", "dortmund": "#fde100",
    "villarreal": "#ffe500", "manchester city": "#6cabdd", "city": "#6cabdd",
    "lille": "#e01e26", "betis": "#0bb861", "real": "#ffffff",
}


def _font(size: int, bold: bool = False):
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    )
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _kickoff(record: dict) -> datetime:
    try:
        return datetime.fromisoformat(record.get("match_utc", "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.max.replace(tzinfo=timezone.utc)


def kickoff_key(record: dict) -> str:
    return _kickoff(record).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")


def build_match_group_message(records, test_mode=False):
    from messages import prediction_message
    return ("🧪 TEST\n" if test_mode else "") + "\n\n".join(prediction_message(r) for r in sorted(records, key=_kickoff))


def _text_width(draw, text, font):
    return draw.textlength(str(text), font=font)


def _rounded(draw, xy, radius=16, fill=None, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _fit_text(draw, text: str, font, max_width: int) -> str:
    text = " ".join(str(text or "").split())
    if _text_width(draw, text, font) <= max_width:
        return text
    while len(text) > 4 and _text_width(draw, text + "…", font) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def _wrap(draw, text: str, font, max_width: int, max_lines: int = 2) -> list[str]:
    words = " ".join(str(text or "").split()).split()
    if not words:
        return ["Veri yok"]
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if not current or _text_width(draw, trial, font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines - 1:
                break
    if current and len(lines) < max_lines:
        remaining_used = sum(len(x.split()) for x in lines) + len(current.split())
        if remaining_used < len(words):
            current = _fit_text(draw, current + " " + " ".join(words[remaining_used:]), font, max_width)
        lines.append(current)
    return lines[:max_lines]


def _team_key(name: str) -> str:
    return (name or "").lower().replace(" fc", "").replace(" cf", "").strip()


def _initials(name: str) -> str:
    parts = [p for p in (name or "").replace("-", " ").split() if p.lower() not in {"fc", "cf", "sk", "fk"}]
    if not parts:
        return "?"
    return (parts[0][:2] if len(parts) == 1 else parts[0][0] + parts[-1][0]).upper()


def _team_color(name: str) -> str:
    key = _team_key(name)
    for token, color in TEAM_COLORS.items():
        if token in key:
            return color
    h = int(hashlib.md5(key.encode()).hexdigest()[:6], 16)
    return f"#{(h>>16)&255:02x}{(h>>8)&255:02x}{h&255:02x}"


def _load_crest(url: str | None, size: int = 72):
    if not url:
        return None
    try:
        import requests
        response = requests.get(url, timeout=4)
        if response.status_code != 200:
            return None
        image = Image.open(io.BytesIO(response.content)).convert("RGBA")
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(image, ((size-image.width)//2, (size-image.height)//2), image)
        return canvas
    except Exception:
        return None


def _crest(record: dict, side: str, size: int = 70):
    name = record.get(f"{side}_team") or side.title()
    ctx = record.get("context") or {}
    side_ctx = ctx.get(side) if isinstance(ctx.get(side), dict) else {}
    for url in (record.get(f"{side}_crest"), record.get(f"{side}_logo"), side_ctx.get("crest"), ctx.get(f"{side}_crest")):
        if isinstance(url, str) and url.startswith("http"):
            image = _load_crest(url, size)
            if image:
                return image
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    color = _team_color(name)
    d.ellipse((1, 1, size-2, size-2), fill=color, outline=GOLD, width=2)
    f = _font(max(18, size//3), True)
    initials = _initials(name)
    box = d.textbbox((0, 0), initials, font=f)
    d.text(((size-(box[2]-box[0]))/2, (size-(box[3]-box[1]))/2-3), initials, font=f, fill=WHITE)
    return image


def _competition_title(record: dict) -> str:
    stage = str((record.get("context") or {}).get("stage") or record.get("stage") or "").upper()
    return "ŞAMPİYONLAR LİGİ" if not stage or "LEAGUE" in stage or "CHAMPIONS" in stage else stage.replace("_", " ")


def _draw_starball(draw, cx: int, cy: int, r: int = 28):
    """Compact Champions-League-style starball mark; local and deterministic."""
    import math
    # outer ball
    draw.ellipse((cx-r-5, cy-r-5, cx+r+5, cy+r+5), outline=MUTED, width=1)
    # six slim stars around a small central polygon, giving a star-ball silhouette
    for j in range(6):
        base = -math.pi/2 + j*math.pi/3
        sx, sy = cx + math.cos(base)*r*0.56, cy + math.sin(base)*r*0.56
        pts=[]
        for i in range(10):
            a = base-math.pi/2 + i*math.pi/5
            rr = r*0.34 if i%2==0 else r*0.14
            pts.append((sx+math.cos(a)*rr, sy+math.sin(a)*rr))
        draw.polygon(pts, outline=WHITE)
    inner=[]
    for i in range(6):
        a=-math.pi/2+i*math.pi/3
        inner.append((cx+math.cos(a)*r*0.24, cy+math.sin(a)*r*0.24))
    draw.polygon(inner, outline=WHITE)

def _draw_seal(draw, cx: int, cy: int, r: int = 58):
    """Project seal: DESIGNED BY / Sercan / FUTBOL • VERİ • ANALİZ • TAHMİN."""
    draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill='#070a0f', outline=GOLD, width=3)
    draw.ellipse((cx-r+7, cy-r+7, cx+r-7, cy+r-7), outline=GOLD, width=1)
    crown_y = cy-r+15
    crown = [(cx-17,crown_y+12),(cx-11,crown_y-1),(cx,crown_y+9),(cx+11,crown_y-1),(cx+17,crown_y+12)]
    draw.line(crown, fill=GOLD, width=2)
    draw.line((cx-17,crown_y+14,cx+17,crown_y+14), fill=GOLD, width=2)
    f1, f2, f3 = _font(9, True), _font(21, True), _font(6, True)
    t='DESIGNED BY'; draw.text((cx-_text_width(draw,t,f1)/2, cy-r+37), t, font=f1, fill=GOLD)
    t='Sercan'; draw.text((cx-_text_width(draw,t,f2)/2, cy-7), t, font=f2, fill=GOLD)
    # Keep the approved wording; split it for readability at Telegram scale.
    t='FUTBOL • VERİ • ANALİZ'; draw.text((cx-_text_width(draw,t,f3)/2, cy+r-24), t, font=f3, fill=GOLD)
    t='• TAHMİN •'; draw.text((cx-_text_width(draw,t,f3)/2, cy+r-15), t, font=f3, fill=GOLD)

def _successful_votes(record: dict) -> list[dict]:
    return [v for v in record.get("ai_votes", []) if v.get("success") and isinstance(v.get("result"), dict)]


def _consensus(record: dict):
    votes = _successful_votes(record)
    if not votes:
        return "Tahmin yok", "—", 0, 0
    outcomes = Counter(v["result"].get("outcome") for v in votes)
    scores = Counter(v["result"].get("score") for v in votes)
    outcome, ov = outcomes.most_common(1)[0]
    score, sv = scores.most_common(1)[0]
    enough = len(votes) >= 3
    winner = label(outcome, record) if enough and ov >= 3 else ("Yetersiz AI katılımı" if not enough else "Ortak karar yok")
    common_score = str(score).replace("-", "–") if enough and ov >= 3 and sv >= 3 and all(v["result"].get("outcome") == outcome for v in votes if v["result"].get("score") == score) else "—"
    return winner, common_score, ov, sv


def _confidence(record: dict) -> int | None:
    vals = []
    for vote in _successful_votes(record):
        try:
            value = vote["result"].get("confidence")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                vals.append(int(value))
        except (TypeError, ValueError):
            pass
    return round(sum(vals)/len(vals)) if vals else None


def _data_status(record: dict) -> list[tuple[str, bool | None]]:
    ctx = record.get("context") or {}
    home, away = ctx.get("home") or {}, ctx.get("away") or {}
    from providers import valid_xi
    official_xi = ctx.get("official_xi") or {}
    predicted = ctx.get("predicted_xi") or {}
    official = all(valid_xi(official_xi.get(side)) for side in ("home", "away"))
    predicted_ok = all(
        valid_xi(official_xi.get(side)) or valid_xi(predicted.get(side))
        for side in ("home", "away")
    ) and not official
    # A non-empty container is not evidence of actual completed matches.
    home_form = home.get("last_5") or {}
    away_form = away.get("last_5") or {}
    form_ok = (isinstance(home_form, dict) and isinstance(away_form, dict)
               and bool(home_form.get("matches")) and bool(away_form.get("matches")))
    standings_ok = bool(home.get("standings")) and bool(away.get("standings"))
    research = record.get("research") or {}
    research_ok = research.get("status") == "OK"
    injuries = research.get("injuries")
    injuries_ok = bool(injuries) if injuries is not None else None
    return [
        ("Resmî XI", official),
        ("Resmî/tahmini XI", predicted_ok if not official else None),
        ("Form", form_ok),
        ("Puan durumu", standings_ok),
        ("Güncel araştırma", research_ok),
        ("Eksik/ceza", injuries_ok),
    ]


def _analysis_lines(record: dict) -> list[str]:
    lines = []
    for vote in _successful_votes(record):
        reason = short_reason(vote.get("result") or {})
        norm = " ".join((reason or "").lower().replace("'", "").split())
        duplicate = any(norm == " ".join(x.lower().replace("'", "").split()) or
                        (len(set(norm.split()) & set(x.lower().split())) >= max(4, min(len(norm.split()), len(x.split())) - 2))
                        for x in lines)
        if reason and reason != "Gerekçe belirtilmedi." and not duplicate:
            lines.append(reason)
        if len(lines) == 2:
            break
    return lines or ["Model gerekçesi bulunmuyor."]


# Image-only ordering: do not mutate ai_votes or archived consensus.
# Valid positive confidence values are subjective model assessments, NOT win odds.
def _vote_confidence(vote: dict) -> float | None:
    if not vote.get("success") or not isinstance(vote.get("result"), dict):
        return None
    value = vote["result"].get("confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    # Providers sometimes use 0 as an absent-value fallback.
    from math import isfinite
    if not isfinite(value) or not 0 < value <= 100:
        return None
    return float(value)


def _ordered_ai_votes(record: dict) -> list[dict]:
    """Descending confidence; missing confidences and failed providers last.

    Original order is retained for ties and unavailable confidences. This is a
    presentation-only projection and NEVER changes stored votes or scoring.
    """
    votes = list(record.get("ai_votes") or [])
    return sorted(votes, key=lambda v: (
        0 if _vote_confidence(v) is not None else 1,
        -(_vote_confidence(v) or 0),
    ))


# Same seven-match single-table composition as the approved visual mockup.
# Match columns, consensus, exact score, five AI score/confidence tiles, notes.
TABLE_X = (20, 340, 525, 675, 1185, 1460)
ROW_HEIGHT = 181
ROW_GAP = 8
HEADER_HEIGHT = 225
TABLE_HEADER_H = 58
FOOTER_H = 108


def _draw_center(draw, xy, text, font, fill):
    x, y = xy
    draw.text((x - _text_width(draw, text, font) / 2, y), text, font=font, fill=fill)


def _display_team(name: str) -> str:
    # Familiar short names are *visual aliases only*, never persisted to match data.
    aliases = {
        "FC Internazionale Milano": "Inter Milano",
        "Club Atlético de Madrid": "Atlético Madrid",
        "Manchester United FC": "Man. United",
        "FC Bayern München": "Bayern Münih",
        "Galatasaray SK": "Galatasaray",
        "FC Barcelona": "Barcelona",
        "Arsenal FC": "Arsenal",
        "Villarreal CF": "Villarreal",
        "SSC Napoli": "Napoli",
        "Lille OSC": "Lille",
        "Club Brugge KV": "Club Brugge",
        "Viking FK": "Viking FK",
    }
    return aliases.get(name, name)


def _draw_header(canvas, draw, records, test_mode: bool) -> int:
    left, right = TABLE_X[0], TABLE_X[-1]
    _rounded(draw, (left, 12, right, HEADER_HEIGHT - 13), 23, PANEL, BORDER, 2)
    _draw_seal(draw, left + 85, 104, 70)
    _draw_starball(draw, left + 218, 88, 39)

    title_font = _font(44, True)
    _draw_center(draw, (770, 34), "ŞAMPİYONLAR LİGİ", title_font, TEXT)
    _draw_center(draw, (770, 91), "MAÇ TAHMİNLERİ", _font(34, True), TEXT)
    local_date = _kickoff(records[0]).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y")
    _draw_center(draw, (770, 145), f"{local_date}   •   {len(records)} MAÇ", _font(22, True), BLUE)
    draw.text((1214, 56), "Disiplinli analiz,", font=_font(19, True), fill=GOLD)
    draw.text((1214, 86), "daha güçlü yarınlar.", font=_font(18, True), fill=GOLD)
    if test_mode:
        _rounded(draw, (1298, 142, 1412, 176), 12, "#33270d", WARN, 2)
        _draw_center(draw, (1355, 148), "TEST", _font(19, True), WARN)
    return HEADER_HEIGHT


def _draw_table_header(draw, y):
    left, right = TABLE_X[0], TABLE_X[-1]
    _rounded(draw, (left, y, right, y + TABLE_HEADER_H), 8, PANEL, BORDER)
    columns = [
        ("MAÇ", None),
        ("ORTAK KARAR", "(1-X-2)"),
        ("TAHMİN SKORU", None),
        ("AI TAHMİNLERİ", "SKOR / GÜVEN %  •  YÜKSEKTEN DÜŞÜĞE"),
        ("KISA ANALİZ", None),
    ]
    for i, (title, subtitle) in enumerate(columns):
        center = (TABLE_X[i] + TABLE_X[i + 1]) / 2
        if subtitle:
            _draw_center(draw, (center, y + 8), title, _font(17, True), TEXT)
            _draw_center(draw, (center, y + 30), subtitle, _font(13, True), MUTED)
        else:
            _draw_center(draw, (center, y + 19), title, _font(15, True), TEXT)
        if i:
            draw.line((TABLE_X[i], y + 9, TABLE_X[i], y + TABLE_HEADER_H - 9), fill=BORDER, width=2)
    return y + TABLE_HEADER_H + 6


def _outcome_color(outcome):
    return {"HOME": GREEN, "AWAY": RED, "DRAW": WARN}.get(outcome, MUTED)


def _draw_match_cell(canvas, draw, y, record):
    x0, x1 = TABLE_X[0], TABLE_X[1]
    # Logos are source URLs already archived with the match; fall back to initials.
    sz = 64
    home = _crest(record, "home", sz)
    away = _crest(record, "away", sz)
    canvas.paste(home, (x0 + 12, y + 30), home)
    canvas.paste(away, (x1 - sz - 12, y + 30), away)
    home_name = _display_team(record.get("home_team", "—"))
    away_name = _display_team(record.get("away_team", "—"))
    fname = _font(18, True)
    name_space = (x1 - sz - 22) - (x0 + sz + 22)
    center = x0 + (x1 - x0) / 2
    _draw_center(draw, (center, y + 41), _fit_text(draw, home_name, fname, name_space), fname, TEXT)
    _draw_center(draw, (center, y + 75), _fit_text(draw, away_name, fname, name_space), fname, TEXT)
    dt = _kickoff(record).astimezone(ZoneInfo("Europe/Istanbul"))
    _draw_center(draw, (center, y + 131), dt.strftime("%d.%m.%Y  %H:%M"), _font(16), MUTED)
    # Explain XI provenance per team without changing the approved table layout.
    from providers import valid_xi
    context = record.get("context") or {}
    official = context.get("official_xi") or {}
    probable = context.get("predicted_xi") or {}
    side_labels = []
    for side in ("home", "away"):
        if valid_xi(official.get(side)):
            side_labels.append("Resmî")
        elif valid_xi(probable.get(side)):
            side_labels.append("Tahmini")
        else:
            side_labels.append("Eksik")
    lineup_label = f"Ev: {side_labels[0]} XI  ·  Dep: {side_labels[1]} XI"
    label_font = _font(12, True)
    _draw_center(draw, (center, y + 154),
                 _fit_text(draw, lineup_label, label_font, x1 - x0 - 14),
                 label_font, GREEN if side_labels == ["Resmî", "Resmî"] else WARN)


def _draw_consensus_cell(draw, y, record):
    x0, x1 = TABLE_X[1], TABLE_X[2]
    votes = _successful_votes(record)
    n = len(votes)
    outcomes = Counter(v.get("result", {}).get("outcome") for v in votes)
    outcome, num = outcomes.most_common(1)[0] if outcomes else (None, 0)
    valid = n >= 3 and num >= 3
    symbol = {"HOME": "1", "AWAY": "2", "DRAW": "X"}.get(outcome) if valid else "—"
    color = _outcome_color(outcome) if valid else MUTED
    cx = (x0 + x1) / 2
    _rounded(draw, (x0 + 15, y + 13, x1 - 15, y + 128), 14, CARD_2, color if valid else BORDER, 2)
    _draw_center(draw, (cx, y + 18), symbol, _font(45, True), color)
    name = (_display_team(label(outcome, record)) if valid else
            "Yetersiz AI" if n < 3 else "Ortak karar yok")
    namef = _font(16, True)
    _draw_center(draw, (cx, y + 81), _fit_text(draw, name, namef, x1 - x0 - 38), namef, color)
    _rounded(draw, (cx - 53, y + 137, cx + 53, y + 166), 10, BLUE_DIM)
    _draw_center(draw, (cx, y + 140), f"{num}/{n} OY" if valid else f"{n}/{max(5, len(record.get('ai_votes') or []), int(record.get('total_ai') or 0))} AI", _font(16, True), BLUE)


def _draw_score_cell(draw, y, record):
    x0, x1 = TABLE_X[2], TABLE_X[3]
    _winner, score, _ov, _sv = _consensus(record)
    # No made-up "probability" is shown beside the consensus score.
    cx = (x0 + x1) / 2
    _rounded(draw, (x0 + 9, y + 13, x1 - 9, y + 166), 12, CARD_2, BORDER)
    _draw_center(draw, (cx, y + 50), score.replace("–", "-"), _font(38, True), TEXT if score != "—" else GOLD)
    if score == "—":
        _draw_center(draw, (cx, y + 111), "Kesin skor yok", _font(13), MUTED)


def _draw_ai_cell(draw, y, record):
    x0, x1 = TABLE_X[3], TABLE_X[4]
    votes = _ordered_ai_votes(record)
    count = min(max(5, len(votes)), 5)
    tile_w = (x1 - x0 - 20) / count
    for i in range(count):
        bx = x0 + 10 + tile_w * i
        end = bx + tile_w - 5
        vote = votes[i] if i < len(votes) else None
        _rounded(draw, (int(bx), y + 14, int(end), y + 166), 11, CARD_2, BORDER)
        model = short_model(vote.get("model", "AI")) if vote else "—"
        model_font = _font(15, True)
        _draw_center(draw, ((bx + end) / 2, y + 28), _fit_text(draw, model, model_font, tile_w - 10), model_font, TEXT)
        if vote and vote.get("success") and isinstance(vote.get("result"), dict):
            result = vote["result"]
            score = str(result.get("score") or "—").replace("–", "-")
            confidence = _vote_confidence(vote)
            tint = _outcome_color(result.get("outcome"))
        else:
            score = "—"
            confidence = None
            tint = MUTED
        _rounded(draw, (int(bx + 8), y + 66, int(end - 8), y + 109), 8, CARD, BORDER)
        _draw_center(draw, ((bx + end) / 2, y + 72), score, _font(24, True), TEXT)
        conf_label = f"%{confidence:g}" if confidence is not None else "—"
        _rounded(draw, (int(bx + 8), y + 116, int(end - 8), y + 157), 8, "#102b28" if confidence is not None else CARD, tint)
        _draw_center(draw, ((bx + end) / 2, y + 123), conf_label, _font(21, True), tint)


def _draw_analysis_cell(draw, y, record):
    x0, x1 = TABLE_X[4], TABLE_X[5]
    af = _font(17)
    yy = y + 29
    for reason in _analysis_lines(record)[:2]:
        for line in _wrap(draw, "• " + reason, af, x1 - x0 - 28, max_lines=2):
            draw.text((x0 + 12, yy), line, font=af, fill=TEXT)
            yy += 24
        yy += 14


def _draw_match_card(canvas, draw, y: int, record: dict, compact: bool) -> int:
    x0, x1 = TABLE_X[0], TABLE_X[-1]
    _rounded(draw, (x0, y, x1, y + ROW_HEIGHT), 14, PANEL, BORDER, 2)
    for x in TABLE_X[1:-1]:
        draw.line((x, y + 9, x, y + ROW_HEIGHT - 9), fill=BORDER, width=2)
    _draw_match_cell(canvas, draw, y, record)
    _draw_consensus_cell(draw, y, record)
    _draw_score_cell(draw, y, record)
    _draw_ai_cell(draw, y, record)
    _draw_analysis_cell(draw, y, record)
    return y + ROW_HEIGHT + ROW_GAP


def _draw_footer(draw, top):
    left, right = TABLE_X[0], TABLE_X[-1]
    _rounded(draw, (left, top, right, top + FOOTER_H - 8), 15, PANEL, BORDER)
    f = _font(17, True)
    cursor = left + 32
    for icon, caption, color in (("1", "Ev sahibi kazanır", GREEN),
                                 ("X", "Beraberlik", WARN),
                                 ("2", "Deplasman kazanır", RED)):
        _rounded(draw, (cursor, top + 15, cursor + 32, top + 46), 6, color)
        _draw_center(draw, (cursor + 16, top + 17), icon, _font(20, True), BG)
        draw.text((cursor + 41, top + 19), caption, font=f, fill=TEXT)
        cursor += 250
    draw.text((left + 800, top + 16), "4/5 AI = Yanıt veren model sayısı", font=_font(15, True), fill=BLUE)
    draw.text((left + 800, top + 44), "— = Yanıt veya güven oranı yok", font=_font(14), fill=MUTED)
    note = "Güven yüzdeleri öznel model değerlendirmesidir, kazanma olasılığı değildir."
    _draw_center(draw, ((left + right)/2, top + 78), note, _font(14), MUTED)


def render_match_group_image(records, test_mode=False):
    """Generate a concise seven-row-style image, with no new AI/API predictions."""
    if not records:
        raise ValueError("Görsel için en az bir maç gerekir.")
    records = sorted(records, key=lambda r: (kickoff_key(r), r.get("home_team", "")))
    header_y = HEADER_HEIGHT
    rows_y = header_y + TABLE_HEADER_H + 6
    footer_y = rows_y + len(records) * (ROW_HEIGHT + ROW_GAP) + 10
    total_h = footer_y + FOOTER_H + 8
    canvas = Image.new("RGB", (WIDTH, total_h), BG)
    draw = ImageDraw.Draw(canvas)
    _draw_header(canvas, draw, records, test_mode)
    _draw_table_header(draw, header_y)
    y = rows_y
    for record in records:
        y = _draw_match_card(canvas, draw, y, record, len(records) > 1)
    _draw_footer(draw, footer_y)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = kickoff_key(records[0]).replace(":", "").replace("-", "")
    key = hashlib.sha256("|".join(str(r.get("match_id", r.get("home_team", ""))) for r in records).encode()).hexdigest()[:10]
    path = REPORT_DIR / f"match_prediction_{stamp}_{key}.png"
    canvas.save(path, optimize=True)
    return path
