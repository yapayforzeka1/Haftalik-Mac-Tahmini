"""Dark modern prediction cards with team logos for Telegram."""
from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from messages import (
    FORMAT_VERSION,
    kickoff_text,
    label,
    prediction_tables,
    short_model,
    short_reason,
)

REPORT_DIR = Path("reports")
WIDTH = 900
PAD = 28

# Dark theme palette matching the approved mockups
BG = "#0b1526"
CARD = "#122033"
CARD_BORDER = "#1c2d45"
TEXT = "#f0f4f8"
MUTED = "#8b9bb0"
TEAL = "#2dd4bf"
TEAL_DIM = "#1a9e8f"
WARN = "#f59e0b"
GREEN = "#22c55e"
WHITE = "#ffffff"

# Simple team colour map for initial-avatar fallback
TEAM_COLORS = {
    "galatasaray": "#a90432",
    "fenerbahce": "#00205b",
    "besiktas": "#1a1a1a",
    "trabzonspor": "#6a1b1b",
    "sporting": "#0a7a3e",
    "benfica": "#e30613",
    "inter": "#0166b1",
    "porto": "#003399",
    "dortmund": "#fde100",
    "villarreal": "#ffe500",
    "manchester city": "#6cabdd",
    "city": "#6cabdd",
    "lille": "#e01e26",
    "betis": "#0bb861",
    "real": "#ffffff",
}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/lato/Lato-Bold.ttf" if bold else "/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
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
    return ("🧪 TEST\n" if test_mode else "") + "\n\n".join(
        prediction_message(r) for r in sorted(records, key=_kickoff)
    )


def _team_key(name: str) -> str:
    return (name or "").lower().replace(" fc", "").replace(" cf", "").strip()


def _initials(name: str) -> str:
    parts = [p for p in (name or "").replace("-", " ").split() if p and p.lower() not in {"fc", "cf", "osc", "sk", "fk"}]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _team_color(name: str) -> str:
    key = _team_key(name)
    for token, color in TEAM_COLORS.items():
        if token in key:
            return color
    # deterministic colour from name
    h = int(hashlib.md5(key.encode()).hexdigest()[:6], 16)
    r, g, b = (h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def _load_crest(url: str | None, size: int = 72) -> Image.Image | None:
    if not url:
        return None
    try:
        import requests
        resp = requests.get(url, timeout=4)
        if resp.status_code != 200:
            return None
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        # pad to square
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        x = (size - img.width) // 2
        y = (size - img.height) // 2
        canvas.paste(img, (x, y), img if img.mode == "RGBA" else None)
        return canvas
    except Exception:
        return None


def _crest_from_record(record: dict, side: str, size: int = 72) -> Image.Image:
    """Return logo image; fall back to coloured initial circle."""
    name = record.get(f"{side}_team") or ("Home" if side == "home" else "Away")
    # try common locations for crest URL
    candidates = [
        record.get(f"{side}_crest"),
        record.get(f"{side}_logo"),
        (record.get("context") or {}).get(side, {}).get("crest") if isinstance((record.get("context") or {}).get(side), dict) else None,
        (record.get("context") or {}).get(f"{side}_crest"),
    ]
    for url in candidates:
        if isinstance(url, str) and url.startswith("http"):
            logo = _load_crest(url, size)
            if logo:
                return logo

    # initial avatar
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = _team_color(name)
    draw.ellipse((0, 0, size - 1, size - 1), fill=color)
    # contrasting text
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    text_color = "#111111" if luminance > 160 else WHITE
    initials = _initials(name)
    font = _font(max(18, size // 3), bold=True)
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2 - 2), initials, font=font, fill=text_color)
    return img


def _rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _text_width(draw, text, font) -> float:
    return draw.textlength(text, font=font)


def _competition_title(record: dict) -> str:
    ctx = record.get("context") or {}
    stage = (ctx.get("stage") or "").upper()
    if "LEAGUE" in stage or "CHAMPIONS" in stage or not stage:
        return "ŞAMPİYONLAR LİGİ"
    return stage.replace("_", " ").title()


def _lineup_status(record: dict) -> tuple[str, str]:
    """Return (icon_color, label)."""
    ctx = record.get("context") or {}
    if (ctx.get("official_xi") or {}).get("status") == "ANNOUNCED":
        return GREEN, "Resmî 11"
    predicted = ctx.get("predicted_xi") or {}
    if all(len(predicted.get(side, [])) == 11 for side in ("home", "away")):
        return WARN, "Tahmini 11"
    return WARN, "Kadro eksik"


def _draw_header(draw, y: int, title: str, badge: str | None = None) -> int:
    font_title = _font(22, bold=True)
    draw.text((PAD, y), title, font=font_title, fill=TEXT)
    if badge:
        font_b = _font(14, bold=True)
        bw = _text_width(draw, badge, font_b) + 20
        bx = WIDTH - PAD - bw
        _rounded_rect(draw, (bx, y - 2, bx + bw, y + 26), 12, fill=CARD, outline=CARD_BORDER)
        draw.text((bx + 10, y + 2), badge, font=font_b, fill=MUTED)
    return y + 40


def _draw_match_title(canvas, draw, y: int, record: dict) -> int:
    home_logo = _crest_from_record(record, "home", 64)
    away_logo = _crest_from_record(record, "away", 64)
    canvas.paste(home_logo, (PAD, y), home_logo)
    canvas.paste(away_logo, (WIDTH - PAD - 64, y), away_logo)

    title = f"{record['home_team']} – {record['away_team']}"
    font = _font(24, bold=True)
    # centre between logos
    max_w = WIDTH - PAD * 2 - 64 * 2 - 24
    # simple truncation if too long
    while _text_width(draw, title, font) > max_w and len(title) > 10:
        title = title[:-2] + "…"
    tw = _text_width(draw, title, font)
    draw.text(((WIDTH - tw) / 2, y + 8), title, font=font, fill=TEXT)

    # time + lineup
    clock = kickoff_text(record)
    color, lineup = _lineup_status(record)
    font_s = _font(16)
    meta = f"🕒  {clock}   ·   {lineup}"
    mw = _text_width(draw, meta, font_s)
    draw.text(((WIDTH - mw) / 2, y + 42), meta, font=font_s, fill=MUTED)
    # green/yellow indicator for lineup
    return y + 78


def _draw_consensus_boxes(draw, y: int, winner: str, winner_votes: str, score: str, score_votes: str) -> int:
    gap = 16
    box_w = (WIDTH - PAD * 2 - gap) // 2
    box_h = 110
    left = PAD
    right = PAD + box_w + gap

    for x, label_txt, value, badge in (
        (left, "ORTAK KAZANAN", winner, winner_votes),
        (right, "ORTAK SKOR", score, score_votes),
    ):
        _rounded_rect(draw, (x, y, x + box_w, y + box_h), 16, fill=CARD, outline=CARD_BORDER)
        font_l = _font(13)
        draw.text((x + 18, y + 14), label_txt, font=font_l, fill=MUTED)
        font_v = _font(26 if label_txt == "ORTAK KAZANAN" else 34, bold=True)
        # centre value
        vw = _text_width(draw, value, font_v)
        draw.text((x + (box_w - vw) / 2, y + 38), value, font=font_v, fill=TEXT)
        # teal pill
        font_p = _font(13, bold=True)
        pw = _text_width(draw, badge, font_p) + 18
        px = x + (box_w - pw) / 2
        py = y + box_h - 32
        _rounded_rect(draw, (px, py, px + pw, py + 22), 11, fill=TEAL)
        draw.text((px + 9, py + 3), badge, font=font_p, fill="#0b1526")
    return y + box_h + 20


def _draw_ai_pills(draw, y: int, models: list[str]) -> int:
    font_l = _font(13)
    draw.text((PAD, y), "SKORU SEÇEN AI’LAR", font=font_l, fill=MUTED)
    y += 26
    font_p = _font(14, bold=True)
    x = PAD
    for name in models:
        pw = _text_width(draw, name, font_p) + 24
        if x + pw > WIDTH - PAD:
            x = PAD
            y += 36
        _rounded_rect(draw, (x, y, x + pw, y + 28), 14, fill=CARD, outline=CARD_BORDER)
        draw.text((x + 12, y + 5), name, font=font_p, fill=TEXT)
        x += pw + 10
    return y + 40


def _draw_footer(draw, y: int, left: str, right: str = "Görsel tasarım örneğidir.") -> int:
    font = _font(13)
    draw.text((PAD, y), left, font=font, fill=MUTED)
    rw = _text_width(draw, right, font)
    draw.text((WIDTH - PAD - rw, y), right, font=font, fill=MUTED)
    return y + 28


def _render_normal(record: dict, test_mode: bool) -> Image.Image:
    """Full consensus (winner + score)."""
    table = record.get("prediction_table") or prediction_tables(record)
    votes = [v for v in record.get("ai_votes", []) if v.get("success") and v.get("result")]
    n = len(votes)
    total = max(5, len(record.get("ai_votes", [])), int(record.get("total_ai") or 0))

    # extract consensus values from table summary if present
    winner, w_votes, score, s_votes = "—", "—", "—", "—"
    models = []
    if table.get("mode") == "NORMAL":
        # summary layout from messages.py
        summary = table.get("summary") or []
        # indices depend on headers; safer to recompute
        from collections import Counter
        outcomes = Counter(v["result"]["outcome"] for v in votes)
        scores = Counter(v["result"]["score"] for v in votes)
        outcome, ov = outcomes.most_common(1)[0]
        score_raw, sv = scores.most_common(1)[0]
        winner = label(outcome, record)
        w_votes = f"{ov}/{n} AI"
        score = score_raw.replace("-", "–")
        s_votes = f"{sv}/{n} AI"
        models = [short_model(v["model"]) for v in votes if v["result"]["score"] == score_raw]
    else:
        # fallback
        winner = "—"
        score = "—"

    height = 420
    if test_mode:
        height += 30
    canvas = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(canvas)
    y = 20
    if test_mode:
        draw.text((PAD, y), "TEST", font=_font(16, bold=True), fill=WARN)
        y += 28

    y = _draw_header(draw, y, _competition_title(record), "ÖRNEK" if test_mode else None)
    y = _draw_match_title(canvas, draw, y, record)
    y = _draw_consensus_boxes(draw, y, winner, w_votes, score, s_votes)
    y = _draw_ai_pills(draw, y, models or ["—"])
    _draw_footer(draw, y, f"{n}/{total} AI yanıtladı")
    return canvas


def _render_individual(record: dict, test_mode: bool) -> Image.Image:
    """Fewer than 3 successful AI responses."""
    table = record.get("prediction_table") or prediction_tables(record)
    votes = [v for v in record.get("ai_votes", []) if v.get("success") and v.get("result")]
    n = len(votes)
    total = max(5, len(record.get("ai_votes", [])), int(record.get("total_ai") or 0))

    row_h = 78
    height = 260 + n * row_h + 60
    if test_mode:
        height += 30
    canvas = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(canvas)
    y = 20
    if test_mode:
        draw.text((PAD, y), "TEST", font=_font(16, bold=True), fill=WARN)
        y += 28

    y = _draw_header(draw, y, _competition_title(record), "BİREYSEL • ÖRNEK" if test_mode else "BİREYSEL")
    y = _draw_match_title(canvas, draw, y, record)

    # response count badge
    font_b = _font(14, bold=True)
    badge = f"{n}/{total} AI yanıtladı"
    bw = _text_width(draw, badge, font_b) + 24
    bx = (WIDTH - bw) / 2
    _rounded_rect(draw, (bx, y, bx + bw, y + 28), 14, fill=CARD, outline=CARD_BORDER)
    draw.text((bx + 12, y + 5), badge, font=font_b, fill=MUTED)
    y += 44

    for v in votes:
        result = v["result"]
        model = short_model(v["model"])
        winner = label(result.get("outcome"), record)
        reason = short_reason(result)
        score = result.get("score", "—").replace("-", "–")

        _rounded_rect(draw, (PAD, y, WIDTH - PAD, y + row_h - 10), 14, fill=CARD, outline=CARD_BORDER)
        font_m = _font(17, bold=True)
        draw.text((PAD + 18, y + 12), model, font=font_m, fill=TEXT)
        font_s = _font(15)
        draw.text((PAD + 18, y + 38), f"{winner}  ·  {reason}", font=font_s, fill=MUTED)
        font_sc = _font(26, bold=True)
        sw = _text_width(draw, score, font_sc)
        draw.text((WIDTH - PAD - 18 - sw, y + 22), score, font=font_sc, fill=TEXT)
        y += row_h

    # warning bar
    y += 8
    _rounded_rect(draw, (PAD, y, WIDTH - PAD, y + 42), 12, fill="#2a1f0a", outline=WARN)
    font_w = _font(14)
    msg = "Üçten az AI yanıtladı; bireysel tahminler gösteriliyor."
    draw.text((PAD + 16, y + 12), "⚠  " + msg, font=font_w, fill=WARN)
    return canvas


def _render_outcome_split(record: dict, test_mode: bool) -> Image.Image:
    """Winner consensus but different scores."""
    table = record.get("prediction_table") or prediction_tables(record)
    votes = [v for v in record.get("ai_votes", []) if v.get("success") and v.get("result")]
    n = len(votes)
    total = max(5, len(record.get("ai_votes", [])), int(record.get("total_ai") or 0))

    from collections import Counter, defaultdict
    outcomes = Counter(v["result"]["outcome"] for v in votes)
    scores = Counter(v["result"]["score"] for v in votes)
    outcome, ov = outcomes.most_common(1)[0]
    winner = label(outcome, record)

    groups = defaultdict(list)
    for v in votes:
        groups[v["result"]["score"]].append(short_model(v["model"]))

    rows = sorted(groups.items(), key=lambda x: -len(x[1]))
    row_h = 52
    height = 300 + len(rows) * row_h + 40
    if test_mode:
        height += 30
    canvas = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(canvas)
    y = 20
    if test_mode:
        draw.text((PAD, y), "TEST", font=_font(16, bold=True), fill=WARN)
        y += 28

    y = _draw_header(draw, y, _competition_title(record))
    y = _draw_match_title(canvas, draw, y, record)

    # winner strip
    _rounded_rect(draw, (PAD, y, WIDTH - PAD, y + 56), 14, fill=CARD, outline=CARD_BORDER)
    font_l = _font(13)
    draw.text((PAD + 18, y + 8), "ORTAK KAZANAN", font=font_l, fill=MUTED)
    font_v = _font(22, bold=True)
    draw.text((PAD + 18, y + 26), f"{winner}  ·  {ov}/{n} AI", font=font_v, fill=TEXT)
    y += 72

    font_h = _font(13)
    draw.text((PAD, y), "SKOR DAĞILIMI", font=font_h, fill=MUTED)
    y += 24

    for score, models in rows:
        score_txt = score.replace("-", "–")
        _rounded_rect(draw, (PAD, y, WIDTH - PAD, y + row_h - 8), 12, fill=CARD, outline=CARD_BORDER)
        font_s = _font(20, bold=True)
        draw.text((PAD + 18, y + 12), score_txt, font=font_s, fill=TEXT)
        font_m = _font(14)
        models_txt = ", ".join(models)
        draw.text((PAD + 110, y + 16), models_txt, font=font_m, fill=MUTED)
        vote = f"{len(models)}/{n}"
        vw = _text_width(draw, vote, font_m)
        draw.text((WIDTH - PAD - 18 - vw, y + 16), vote, font=font_m, fill=TEAL)
        y += row_h

    _draw_footer(draw, y + 8, f"{n}/{total} AI yanıtladı")
    return canvas


def _render_unavailable(record: dict, test_mode: bool) -> Image.Image:
    height = 220
    canvas = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(canvas)
    y = 24
    if test_mode:
        draw.text((PAD, y), "TEST", font=_font(16, bold=True), fill=WARN)
        y += 28
    y = _draw_header(draw, y, _competition_title(record))
    y = _draw_match_title(canvas, draw, y, record)
    _rounded_rect(draw, (PAD, y, WIDTH - PAD, y + 56), 14, fill="#2a1a1a", outline="#7f1d1d")
    font = _font(16, bold=True)
    draw.text((PAD + 20, y + 18), "Tahmin üretilemedi — AI yanıtı yok", font=font, fill="#fca5a5")
    return canvas


def _render_record(record: dict, test_mode: bool = False) -> Image.Image:
    table = record.get("prediction_table") or prediction_tables(record)
    mode = table.get("mode", "NO_COMMON")
    if mode == "UNAVAILABLE" or record.get("prediction_kind") in {"UNAVAILABLE", "STATISTICAL"}:
        return _render_unavailable(record, test_mode)
    if mode == "NORMAL":
        return _render_normal(record, test_mode)
    if mode == "INDIVIDUAL" or mode == "NO_COMMON":
        # NO_COMMON also shows per-model for clarity
        return _render_individual(record, test_mode)
    if mode == "OUTCOME_COMMON_SCORE_SPLIT":
        return _render_outcome_split(record, test_mode)
    return _render_individual(record, test_mode)


def render_match_group_image(records, test_mode=False):
    """Render one or more matches into a single dark card image."""
    if not records:
        raise ValueError("Görsel için en az bir maç gerekir.")
    records = sorted(records, key=_kickoff)

    # multi-match: stack individual cards with small gap
    images = [_render_record(r, test_mode) for r in records]
    gap = 16
    total_h = sum(im.height for im in images) + gap * (len(images) - 1) + 24
    # add a top competition banner when multiple matches
    banner_h = 52 if len(images) > 1 else 0
    canvas = Image.new("RGB", (WIDTH, total_h + banner_h), BG)
    draw = ImageDraw.Draw(canvas)
    y = 0
    if len(images) > 1:
        title = _competition_title(records[0])
        font = _font(20, bold=True)
        draw.text((PAD, 16), title, font=font, fill=TEXT)
        sub = f"{len(images)} MAÇ"
        font_s = _font(14)
        sw = _text_width(draw, sub, font_s)
        draw.text((WIDTH - PAD - sw, 20), sub, font=font_s, fill=MUTED)
        y = banner_h

    for im in images:
        canvas.paste(im, (0, y))
        y += im.height + gap

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = kickoff_key(records[0]).replace(":", "").replace("-", "")
    key = hashlib.sha256(
        "|".join(str(r.get("match_id", r.get("home_team", ""))) for r in records).encode()
    ).hexdigest()[:10]
    path = REPORT_DIR / f"match_prediction_{stamp}_{key}.png"
    canvas.save(path, optimize=True)
    return path
