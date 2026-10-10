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
WIDTH = 900
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
    official = (ctx.get("official_xi") or {}).get("status") == "ANNOUNCED"
    predicted = ctx.get("predicted_xi") or {}
    predicted_ok = all(len(predicted.get(side, [])) == 11 for side in ("home", "away"))
    form_ok = bool(home.get("last_5")) and bool(away.get("last_5"))
    standings_ok = bool(home.get("standings")) and bool(away.get("standings"))
    research = record.get("research") or {}
    research_ok = research.get("status") == "OK"
    injuries = research.get("injuries")
    injuries_ok = bool(injuries) if injuries is not None else None
    return [
        ("Resmî XI", official),
        ("Tahmini XI", predicted_ok if not official else None),
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


def _draw_header(canvas, draw, records, test_mode: bool) -> int:
    h = 154
    _rounded(draw, (PAD, 18, WIDTH-PAD, h-4), 22, fill=PANEL, outline=BORDER, width=2)
    _draw_seal(draw, PAD+70, 83, 56)
    _draw_starball(draw, PAD+157, 58, 23)
    title_f, sub_f = _font(27, True), _font(15)
    title = _competition_title(records[0])
    draw.text((PAD+195, 38), title, font=title_f, fill=TEXT)
    dt = _kickoff(records[0]).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y")
    sub = f"MAÇ TAHMİNLERİ  •  {dt}  •  {len(records)} MAÇ" if len(records) > 1 else f"MAÇ TAHMİNİ  •  {dt}"
    draw.text((PAD+195, 80), sub, font=sub_f, fill=MUTED)
    motto = "Disiplinli analiz, daha güçlü yarınlar."
    mf = _font(13, True)
    mw = _text_width(draw, motto, mf)
    draw.text((WIDTH-PAD-24-mw, 56), motto, font=mf, fill=GOLD)
    if test_mode:
        tf = _font(13, True); t="TEST"
        _rounded(draw, (WIDTH-PAD-85, 90, WIDTH-PAD-24, 116), 12, fill="#33270d", outline=WARN)
        draw.text((WIDTH-PAD-74, 95), t, font=tf, fill=WARN)
    return h + 10


def _draw_model_rows(draw, x, y, w, record) -> int:
    votes = _successful_votes(record)
    title_f, row_f, score_f = _font(12, True), _font(13), _font(14, True)
    draw.text((x, y), "AI TAHMİNLERİ", font=title_f, fill=MUTED); y += 22
    if not votes:
        draw.text((x, y), "AI yanıtı yok", font=row_f, fill=RED)
        return y + 28
    for vote in votes[:5]:
        result = vote["result"]
        model = short_model(vote.get("model", "AI"))
        outcome = label(result.get("outcome"), record)
        score = str(result.get("score") or "—").replace("-", "–")
        conf = result.get("confidence")
        # Several providers use zero as a fallback when confidence is absent.
        # Show it as unavailable instead of implying measured 0% confidence.
        conf_txt = f" %{conf:g}" if isinstance(conf, (int, float)) and not isinstance(conf, bool) and conf > 0 else " —"
        draw.text((x, y), _fit_text(draw, f"{model}: {outcome}", row_f, w-105), font=row_f, fill=TEXT)
        right = f"{score}{conf_txt}"
        rw = _text_width(draw, right, score_f)
        draw.text((x+w-rw, y), right, font=score_f, fill=BLUE)
        y += 25
    return y


def _draw_data_status(draw, x, y, w, record) -> int:
    draw.text((x, y), "VERİ DURUMU", font=_font(12, True), fill=MUTED); y += 23
    f = _font(12, True)
    cx = x
    for name, state in _data_status(record):
        if state is None:
            continue
        text = ("✓ " if state else "× ") + name
        color = GREEN if state else WARN
        pill_w = _text_width(draw, text, f) + 20
        if cx + pill_w > x + w:
            cx = x; y += 30
        _rounded(draw, (cx, y, cx+pill_w, y+24), 12, fill=CARD_2, outline=color)
        draw.text((cx+10, y+4), text, font=f, fill=color)
        cx += pill_w + 8
    return y + 31


def _draw_match_card(canvas, draw, y: int, record: dict, compact: bool) -> int:
    card_h = 520
    x1, x2 = PAD, WIDTH-PAD
    _rounded(draw, (x1, y, x2, y+card_h), 22, fill=PANEL, outline=BORDER, width=2)

    logo_size = 64
    home_logo, away_logo = _crest(record, "home", logo_size), _crest(record, "away", logo_size)
    canvas.paste(home_logo, (x1+22, y+24), home_logo)
    canvas.paste(away_logo, (x2-22-logo_size, y+24), away_logo)
    name_f = _font(22, True)
    match = f"{record.get('home_team','—')}  –  {record.get('away_team','—')}"
    match = _fit_text(draw, match, name_f, 690)
    mw = _text_width(draw, match, name_f)
    draw.text(((WIDTH-mw)/2, y+27), match, font=name_f, fill=TEXT)
    meta = f"{kickoff_text(record)}  •  90 dakika"
    mf = _font(13); mwidth = _text_width(draw, meta, mf)
    draw.text(((WIDTH-mwidth)/2, y+62), meta, font=mf, fill=MUTED)

    winner, score, ov, sv = _consensus(record)
    votes = _successful_votes(record); n = len(votes)
    conf = _confidence(record)
    box_y = y + 108
    gap = 14; bw = (x2-x1-44-gap)/2
    for bx, label_txt, value, sub in (
        (x1+22, "KONSENSÜS", winner, f"{ov}/{n} AI" if n else "0 AI"),
        (x1+22+bw+gap, "TAHMİNİ SKOR", score, (f"Güven %{conf}" if conf is not None else "Güven verisi yok") if score != "—" else "Nihai tahmin oluşmadı"),
    ):
        _rounded(draw, (bx, box_y, bx+bw, box_y+92), 15, fill=CARD, outline=BORDER)
        draw.text((bx+15, box_y+12), label_txt, font=_font(11, True), fill=MUTED)
        vf = _font(24 if label_txt == "KONSENSÜS" else 31, True)
        value_fit = _fit_text(draw, value, vf, int(bw-30))
        draw.text((bx+15, box_y+35), value_fit, font=vf, fill=TEXT if score != "—" else WARN)
        sw = _text_width(draw, sub, _font(11, True))
        draw.text((bx+bw-15-sw, box_y+69), sub, font=_font(11, True), fill=BLUE)

    split_y = box_y + 112
    left_x, right_x = x1+22, WIDTH//2+8
    col_w = WIDTH//2 - PAD - 38
    model_rows_bottom = _draw_model_rows(draw, left_x, split_y, col_w, record)

    draw.text((right_x, split_y), "KISA ANALİZ", font=_font(12, True), fill=MUTED)
    ay = split_y + 23
    af = _font(12)
    for reason in _analysis_lines(record):
        for line in _wrap(draw, "• " + reason, af, col_w, 2):
            draw.text((right_x, ay), line, font=af, fill=TEXT); ay += 20
        ay += 3

    # Keep the data badges below all five model rows, with room for wrapping.
    data_y = y + card_h - 130
    data_y = max(data_y, model_rows_bottom + 20)
    _draw_data_status(draw, x1+22, data_y, x2-x1-44, record)
    footer = f"{n}/{max(5, len(record.get('ai_votes', [])), int(record.get('total_ai') or 0))} AI yanıtladı"
    draw.text((x2-22-_text_width(draw, footer, _font(11)), y+card_h-27), footer, font=_font(11), fill=MUTED)
    return y + card_h + 16


def render_match_group_image(records, test_mode=False):
    """Render one match or all ready matches sharing the same kickoff into one image."""
    if not records:
        raise ValueError("Görsel için en az bir maç gerekir.")
    records = sorted(records, key=lambda r: (kickoff_key(r), r.get("home_team", "")))
    compact = len(records) > 1
    card_h = 520
    header_h = 164
    total_h = header_h + len(records) * (card_h + 16) + 34
    canvas = Image.new("RGB", (WIDTH, total_h), BG)
    draw = ImageDraw.Draw(canvas)
    y = _draw_header(canvas, draw, records, test_mode)
    for record in records:
        y = _draw_match_card(canvas, draw, y, record, compact)
    footer = "AI destekli analiz • Güncel veri • Çoklu model konsensüsü"
    fw = _text_width(draw, footer, _font(11, True))
    draw.text(((WIDTH-fw)/2, total_h-25), footer, font=_font(11, True), fill=MUTED)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = kickoff_key(records[0]).replace(":", "").replace("-", "")
    key = hashlib.sha256("|".join(str(r.get("match_id", r.get("home_team", ""))) for r in records).encode()).hexdigest()[:10]
    path = REPORT_DIR / f"match_prediction_{stamp}_{key}.png"
    canvas.save(path, optimize=True)
    return path