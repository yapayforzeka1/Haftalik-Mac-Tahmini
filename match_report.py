from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

SEASON = "2026/27"
REPORT_DIR = Path("reports")
MODEL_ORDER = [
    "Gemini 3.6 Flash",
    "Mistral Small Latest",
    "Groq Qwen 3.6 27B",
    "Cohere Command A+",
    "Groq GPT-OSS 120B",
]
MODEL_SHORT = {
    "Gemini 3.6 Flash": "GEMINI",
    "Mistral Small Latest": "MISTRAL",
    "Groq Qwen 3.6 27B": "QWEN",
    "Cohere Command A+": "COHERE",
    "Groq GPT-OSS 120B": "GPT-OSS",
}


def _font(size: int, bold: bool = False):
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _center(draw: ImageDraw.ImageDraw, box, text: str, font, fill):
    x1, y1, x2, y2 = box
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - 2), text, font=font, fill=fill)


def _short_team(name: str, max_len: int = 22) -> str:
    name = str(name)
    return name if len(name) <= max_len else name[: max_len - 1] + "…"


def _kickoff(record: dict[str, Any]) -> datetime:
    value = record.get("match_utc")
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
    value = record.get("match_time")
    try:
        return datetime.strptime(str(value), "%d.%m.%Y %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.max.replace(tzinfo=timezone.utc)


def kickoff_key(record: dict[str, Any]) -> str:
    dt = _kickoff(record)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")


def _turkey_date_time(record: dict[str, Any]) -> tuple[str, str]:
    # Stored match_utc is authoritative. Display is handled in Europe/Istanbul by the bot data.
    value = record.get("match_time")
    if value:
        try:
            dt = datetime.strptime(str(value), "%d.%m.%Y %H:%M")
            return dt.strftime("%d.%m.%Y"), dt.strftime("%H:%M")
        except ValueError:
            pass
    dt = _kickoff(record).astimezone(ZoneInfo("Europe/Istanbul"))
    return dt.strftime("%d.%m.%Y"), dt.strftime("%H:%M")


def _outcome_label(record: dict[str, Any]) -> str:
    c = record.get("consensus") or {}
    outcome = c.get("outcome")
    if outcome == "HOME":
        return str(record.get("home_team", "Ev sahibi"))
    if outcome == "AWAY":
        return str(record.get("away_team", "Deplasman"))
    return "Beraberlik"


def build_match_group_message(records: list[dict[str, Any]], test_mode: bool = False) -> str:
    if not records:
        return ""
    records = sorted(records, key=_kickoff)
    first = records[0]
    date_text, time_text = _turkey_date_time(first)
    prefix = "🧪 TEST MODU\n\n" if test_mode else ""

    if len(records) == 1:
        header = "🏆 ŞAMPİYONLAR LİGİ 2026/27\n⚽ MAÇ TAHMİNİ"
    else:
        header = f"🏆 ŞAMPİYONLAR LİGİ 2026/27\n⚽ {len(records)} MAÇLIK AI TAHMİN PAKETİ"

    lines = [
        header,
        f"📅 {date_text}   ⏰ {time_text}",
        "",
    ]

    for index, record in enumerate(records):
        home = record.get("home_team", "-")
        away = record.get("away_team", "-")
        c = record.get("consensus") or {}
        successful = int(c.get("successful_ai") or 0)
        outcome_votes = int(c.get("outcome_votes") or 0)
        score_votes = int(c.get("score_votes") or 0)
        outcome_share = int(c.get("outcome_share") or 0)
        confidence = int(c.get("average_subjective_confidence") or 0)
        score_share = int(c.get("score_share") or 0)
        outcome = _outcome_label(record)
        score = str(c.get("score") or "-")

        lines.append(f"⚽ {home} — {away}")
        lines.append(f"🤖 AI Ortak Kararı: {outcome} — Uzlaşma %{outcome_share} ({outcome_votes}/{successful})")
        lines.append(f"🎯 Skor: {score} — Uzlaşma %{score_share} ({score_votes}/{successful})")
        lines.append(f"📊 AI Güveni: %{confidence} — öznel güven")
        if index != len(records) - 1:
            lines.append("\n━━━━━━━━━━━━━━━━━━\n")

    lines.extend([
        "",
        "ℹ️ Bu oranlar maç öncesi yapay zekâların ortak kararını gösterir.",
        "Puanlama maç sonucu belli olduktan sonra yapılacaktır.",
    ])
    return prefix + "\n".join(lines)


def _draw_team_badge(draw, cx: int, cy: int, team: str, radius: int = 48):
    # Lightweight local badge: avoids downloading logos and keeps GitHub Actions deterministic.
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(10, 26, 48), outline=(65, 180, 245), width=3)
    initials = "".join(part[0] for part in team.replace("/", " ").split()[:2]).upper() or "?"
    _center(draw, (cx - radius, cy - radius, cx + radius, cy + radius), initials[:3], _font(27, True), (245, 245, 245))


def _draw_match_card(draw, box, record: dict[str, Any], compact: bool):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=18, fill=(6, 19, 37), outline=(39, 104, 158), width=2)
    home = _short_team(record.get("home_team", "-"), 20 if compact else 26)
    away = _short_team(record.get("away_team", "-"), 20 if compact else 26)
    c = record.get("consensus") or {}
    outcome = _outcome_label(record)
    score = str(c.get("score") or "-")
    successful = int(c.get("successful_ai") or 0)
    outcome_votes = int(c.get("outcome_votes") or 0)
    score_votes = int(c.get("score_votes") or 0)
    outcome_share = int(c.get("outcome_share") or 0)
    score_share = int(c.get("score_share") or 0)
    confidence = int(c.get("average_subjective_confidence") or 0)

    if compact:
        top = y1 + 20
        _center(draw, (x1 + 12, top, x2 - 12, top + 38), f"{home}   VS   {away}", _font(21, True), (242, 245, 250))
        _draw_team_badge(draw, x1 + 75, y1 + 88, home, 34)
        _draw_team_badge(draw, x2 - 75, y1 + 88, away, 34)
        _center(draw, (x1 + 115, y1 + 68, x2 - 115, y1 + 108), "AI TAHMİNİ", _font(13, True), (74, 205, 255))
        _center(draw, (x1 + 20, y1 + 128, x2 - 20, y1 + 163), f"{outcome}  •  Uzlaşma %{outcome_share} ({outcome_votes}/{successful})", _font(18, True), (80, 225, 255))
        _center(draw, (x1 + 20, y1 + 164, x2 - 20, y1 + 200), f"Skor  {score}  •  Uzlaşma %{score_share} ({score_votes}/{successful})", _font(17, True), (255, 215, 70))
        draw.text((x1 + 18, y2 - 30), f"AI Ortak Kararı  •  Öznel güven %{confidence}", font=_font(12, True), fill=(205, 218, 232))
    else:
        _center(draw, (x1 + 15, y1 + 18, x2 - 15, y1 + 58), f"{home}   VS   {away}", _font(27, True), (242, 245, 250))
        _draw_team_badge(draw, x1 + 110, y1 + 115, home, 55)
        _draw_team_badge(draw, x2 - 110, y1 + 115, away, 55)
        _center(draw, (x1 + 180, y1 + 86, x2 - 180, y1 + 142), "AI TAHMİNİ", _font(15, True), (74, 205, 255))
        _center(draw, (x1 + 30, y1 + 160, x2 - 30, y1 + 205), f"Kazanan: {outcome}  •  Uzlaşma %{outcome_share} ({outcome_votes}/{successful})", _font(22, True), (80, 225, 255))
        _center(draw, (x1 + 30, y1 + 208, x2 - 30, y1 + 250), f"Skor: {score}  •  Uzlaşma %{score_share} ({score_votes}/{successful})", _font(21, True), (255, 215, 70))
        draw.text((x1 + 25, y2 - 42), f"AI Ortak Kararı   •   Öznel güven: %{confidence}", font=_font(15, True), fill=(205, 218, 232))


def render_match_group_image(records: list[dict[str, Any]], test_mode: bool = False) -> Path:
    if not records:
        raise ValueError("Görsel için en az bir maç gerekir.")
    records = sorted(records, key=_kickoff)
    multi = len(records) > 1
    width = 1900 if multi else 1500
    if multi:
        card_w = 890
        card_h = 300
        rows = (len(records) + 1) // 2
        height = 310 + rows * (card_h + 24) + 85
    else:
        card_w = 1240
        card_h = 420
        height = 820

    image = Image.new("RGB", (width, height), (3, 9, 20))
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, width, 150), fill=(6, 16, 32), outline=(32, 150, 220), width=2)
    draw.text((55, 24), "ŞAMPİYONLAR LİGİ 2026/27", font=_font(39, True), fill=(245, 247, 250))
    subtitle = "AI MAÇ TAHMİNİ" if not multi else f"{len(records)} MAÇLIK AI TAHMİN PAKETİ"
    draw.text((55, 88), subtitle, font=_font(23, True), fill=(72, 205, 255))

    date_text, time_text = _turkey_date_time(records[0])
    draw.text((width - 500, 46), f"{date_text}  •  {time_text}", font=_font(19, True), fill=(235, 238, 242))
    draw.ellipse((width - 120, 28, width - 55, 93), outline=(50, 190, 255), width=3)
    draw.text((width - 107, 47), "CL", font=_font(23, True), fill=(255, 215, 70))

    y = 190
    for i, record in enumerate(records):
        if multi:
            col = i % 2
            row = i // 2
            x = 35 + col * (card_w + 20)
            yy = y + row * (card_h + 24)
            _draw_match_card(draw, (x, yy, x + card_w, yy + card_h), record, compact=True)
        else:
            x = (width - card_w) // 2
            _draw_match_card(draw, (x, y, x + card_w, y + card_h), record, compact=False)

    footer_y = height - 66
    draw.text((45, footer_y), "Uzlaşma gerçek olasılık değildir. Kapsam: 90 dakika + hakem ek süresi. Puanlama maç sonrası yapılır.", font=_font(16, True), fill=(155, 188, 215))
    if test_mode:
        draw.text((width - 260, footer_y), "TEST MODU", font=_font(17, True), fill=(255, 210, 70))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = kickoff_key(records[0]).replace(":", "").replace("-", "")
    suffix = "multi" if multi else "single"
    path = REPORT_DIR / f"match_prediction_{stamp}_{suffix}.png"
    image.save(path, optimize=True)
    return path
