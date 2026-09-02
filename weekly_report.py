from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

WEEKLY_REPORTS_FILE = Path("weekly_reports.json")
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


def load_weekly_reports() -> dict[str, Any]:
    if not WEEKLY_REPORTS_FILE.exists():
        return {}
    try:
        return json.loads(WEEKLY_REPORTS_FILE.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"⚠️ {WEEKLY_REPORTS_FILE} okunamadı: {error}")
        return {}


def save_weekly_reports(data: dict[str, Any]) -> None:
    temp = WEEKLY_REPORTS_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(WEEKLY_REPORTS_FILE)


def _font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = str(text).split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _score_text(points: int | None) -> str:
    return "-" if points is None else str(points)


def _team_short(name: str) -> str:
    return name.replace(" FC", "").replace(" AFC", "")


def weekly_rows(predictions: dict[str, Any], matchday: int) -> list[dict[str, Any]]:
    rows = []
    for record in predictions.values():
        if int(record.get("matchday") or 0) != int(matchday):
            continue
        if not record.get("actual"):
            continue
        rows.append(record)
    def kickoff_key(record: dict[str, Any]) -> datetime:
        value = record.get("match_utc")
        if value:
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                pass
        try:
            return datetime.strptime(record.get("match_time", "31.12.2099 23:59"), "%d.%m.%Y %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.max.replace(tzinfo=timezone.utc)

    rows.sort(key=kickoff_key)
    return rows


def _stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, dict[str, int | float]] = {}
    for model in MODEL_ORDER:
        stats[model] = {"matches": 0, "points": 0, "exact": 0, "outcome": 0}
    consensus = {"matches": 0, "points": 0, "exact": 0, "outcome": 0}

    for record in records:
        actual = record.get("actual") or {}
        ah, aa = actual.get("home"), actual.get("away")
        if ah is None or aa is None:
            continue
        if record.get("consensus_points") is not None:
            consensus["matches"] += 1
            consensus["points"] += int(record["consensus_points"])
            consensus["exact"] += int(bool(record.get("exact_score_correct")))
            consensus["outcome"] += int(bool(record.get("outcome_correct")))
        for vote in record.get("ai_votes", []):
            model = vote.get("model")
            if model not in stats or not vote.get("success") or vote.get("points") is None:
                continue
            item = stats[model]
            item["matches"] += 1
            item["points"] += int(vote["points"])
            item["exact"] += int(bool(vote.get("exact_score_correct")))
            item["outcome"] += int(bool(vote.get("outcome_correct")))

    for item in stats.values():
        n = int(item["matches"])
        item["avg"] = round(item["points"] / n, 2) if n else 0
    consensus["avg"] = round(consensus["points"] / consensus["matches"], 2) if consensus["matches"] else 0
    return {"models": stats, "consensus": consensus}


def build_weekly_snapshot(predictions: dict[str, Any], matchday: int, planned_matches: list[dict[str, Any]]) -> dict[str, Any]:
    records = weekly_rows(predictions, matchday)
    stats = _stats(records)
    planned = [m for m in planned_matches if int(m.get("matchday") or 0) == int(matchday)]
    completed_ids = [str(r.get("match_id")) for r in records]
    postponed = []
    for match in planned:
        if str(match.get("id")) in completed_ids:
            continue
        status = match.get("status") or ""
        if status in {"POSTPONED", "CANCELLED", "SUSPENDED", "ABANDONED"}:
            postponed.append({"match_id": str(match.get("id")), "home": match.get("homeTeam", {}).get("name"), "away": match.get("awayTeam", {}).get("name"), "status": status})

    return {
        "season": "2026/27",
        "matchday": int(matchday),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "planned_matches": len(planned),
        "completed_evaluated_matches": len(records),
        "postponed_or_unavailable": postponed,
        "match_ids": completed_ids,
        "stats": stats,
    }


def build_general_snapshot(weekly_reports: dict[str, Any]) -> dict[str, Any]:
    by_model: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "weeks": {}, "total_points": 0, "matches": 0, "exact": 0, "outcome": 0
    })
    consensus = {"weeks": {}, "total_points": 0, "matches": 0, "exact": 0, "outcome": 0}

    for key, report in sorted(weekly_reports.items(), key=lambda kv: int(kv[0])):
        week = int(key)
        stats = report.get("stats", {})
        model_stats = stats.get("models", {})
        for model in MODEL_ORDER:
            item = model_stats.get(model, {})
            target = by_model[model]
            target["weeks"][str(week)] = int(item.get("points", 0))
            target["total_points"] += int(item.get("points", 0))
            target["matches"] += int(item.get("matches", 0))
            target["exact"] += int(item.get("exact", 0))
            target["outcome"] += int(item.get("outcome", 0))

        c = stats.get("consensus", {})
        consensus["weeks"][str(week)] = int(c.get("points", 0))
        consensus["total_points"] += int(c.get("points", 0))
        consensus["matches"] += int(c.get("matches", 0))
        consensus["exact"] += int(c.get("exact", 0))
        consensus["outcome"] += int(c.get("outcome", 0))

    for target in by_model.values():
        target["avg"] = round(target["total_points"] / target["matches"], 2) if target["matches"] else 0
    consensus["avg"] = round(consensus["total_points"] / consensus["matches"], 2) if consensus["matches"] else 0
    return {"models": dict(by_model), "consensus": consensus}


def _draw_header(draw, image, title: str, subtitle: str):
    width = image.width
    draw.rectangle((0, 0, width, 150), fill=(10, 18, 35), outline=(30, 150, 220), width=2)
    draw.text((45, 28), title, font=_font(34, True), fill=(245, 245, 245))
    draw.text((45, 86), subtitle, font=_font(20), fill=(130, 205, 255))


def render_weekly_image(snapshot: dict[str, Any], predictions: dict[str, Any]) -> Path:
    matchday = int(snapshot["matchday"])
    records = weekly_rows(predictions, matchday)
    width = 1900
    row_h = 145
    height = 230 + max(1, len(records)) * row_h + 480
    image = Image.new("RGB", (width, height), (5, 10, 20))
    draw = ImageDraw.Draw(image)
    _draw_header(draw, image, "ŞAMPİYONLAR LİGİ 2026/27", f"HAFTALIK YAPAY ZEKA PERFORMANS RAPORU  •  MATCHDAY {matchday}")

    y = 180
    headers = ["MAÇ", "GERÇEK", *[MODEL_SHORT[m] for m in MODEL_ORDER], "KONSENSÜS"]
    col_x = [35, 555, 700, 915, 1130, 1345, 1560, 1775]
    col_w = [500, 125, 195, 195, 195, 195, 195, 110]
    for x, h in zip(col_x, headers):
        draw.rectangle((x, y, x + col_w[headers.index(h)], y + 52), fill=(18, 36, 60), outline=(55, 110, 155), width=1)
        draw.text((x + 10, y + 12), h, font=_font(17, True), fill=(240, 240, 240))
    y += 52

    for record in records:
        actual = record["actual"]
        actual_score = f"{actual['home']}-{actual['away']}"
        match_name = f"{_team_short(record['home_team'])} - {_team_short(record['away_team'])}"
        cells = [match_name, actual_score]
        votes = {v.get("model"): v for v in record.get("ai_votes", [])}
        for model in MODEL_ORDER:
            vote = votes.get(model)
            if not vote or not vote.get("success"):
                cells.append("YOK\n-")
            else:
                cells.append(f"{vote['result'].get('score', '-') }\n{_score_text(vote.get('points'))} PUAN")
        cells.append(f"{record.get('consensus', {}).get('score', '-')}\n{_score_text(record.get('consensus_points'))} PUAN")
        for i, text in enumerate(cells):
            x = col_x[i]
            w = col_w[i]
            draw.rectangle((x, y, x + w, y + row_h), fill=(8, 16, 28), outline=(42, 72, 98), width=1)
            if i == 0:
                f = _font(20, True)
            elif i == 1:
                f = _font(28, True)
            else:
                f = _font(18, True)
            lines = str(text).split("\n")
            yy = y + 28
            for line in lines:
                draw.text((x + 10, yy), line, font=f, fill=(235, 235, 235))
                yy += 34
        y += row_h

    y += 35
    draw.text((35, y), "YAPAY ZEKA HAFTALIK ÖZET PERFORMANSI", font=_font(27, True), fill=(255, 205, 60))
    y += 50
    stats = snapshot["stats"]["models"]
    card_w = 350
    for idx, model in enumerate(MODEL_ORDER):
        row = idx // 3
        col = idx % 3
        x = 35 + col * 385
        yy = y + row * 145
        item = stats[model]
        draw.rectangle((x, yy, x + card_w, yy + 125), fill=(12, 23, 39), outline=(55, 125, 175), width=2)
        draw.text((x + 15, yy + 12), MODEL_SHORT[model], font=_font(22, True), fill=(245, 245, 245))
        draw.text((x + 15, yy + 50), f"{item['points']} PUAN  •  {item['matches']} MAÇ", font=_font(19, True), fill=(130, 220, 255))
        draw.text((x + 15, yy + 82), f"Sonuç: {item['outcome']}  •  Tam skor: {item['exact']}  •  Ort: {item['avg']}", font=_font(15), fill=(220, 220, 220))
    cons = snapshot["stats"]["consensus"]
    yy = y + 2 * 145
    draw.rectangle((35, yy, 35 + 1155, yy + 125), fill=(25, 25, 15), outline=(220, 170, 30), width=2)
    draw.text((55, yy + 18), "KONSENSÜS (5 AI ORTAK)", font=_font(23, True), fill=(255, 220, 90))
    draw.text((55, yy + 60), f"{cons['points']} PUAN  •  {cons['matches']} MAÇ  •  Sonuç: {cons['outcome']}  •  Tam skor: {cons['exact']}  •  Ort: {cons['avg']}", font=_font(18, True), fill=(245, 245, 245))

    postponed = snapshot.get("postponed_or_unavailable") or []
    if postponed:
        text = "Ertelenen/uygulanamayan maçlar: " + ", ".join(f"{p['home']} - {p['away']} ({p['status']})" for p in postponed)
        draw.text((35, height - 55), text[:190], font=_font(14), fill=(255, 190, 90))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"matchday_{matchday}_weekly.png"
    image.save(path)
    return path


def render_general_image(weekly_reports: dict[str, Any]) -> Path:
    general = build_general_snapshot(weekly_reports)
    weeks = sorted({w for model in general["models"].values() for w in model["weeks"]}, key=int)
    width = max(1700, 35 + 300 + 150 * len(weeks) + 210 + 170 + 35)
    row_h = 72
    row_count = len(MODEL_ORDER) + 1
    height = 250 + row_count * row_h + 300
    image = Image.new("RGB", (width, height), (5, 10, 20))
    draw = ImageDraw.Draw(image)
    _draw_header(draw, image, "ŞAMPİYONLAR LİGİ 2026/27", "GENEL PERFORMANS  •  HAFTALAR AYRI, SEZON TOPLAMI KÜMÜLATİF")

    y = 180
    x0 = 35
    cols = ["AI MODELİ", *[f"{w}. HAFTA" for w in weeks], "SEZON TOPLAM", "ORT. PUAN"]
    widths = [300] + [150] * len(weeks) + [210, 170]
    x = x0
    for i, h in enumerate(cols):
        draw.rectangle((x, y, x + widths[i], y + 52), fill=(18, 36, 60), outline=(55, 110, 155), width=1)
        draw.text((x + 10, y + 13), h, font=_font(15, True), fill=(240, 240, 240))
        x += widths[i]
    y += 52

    def draw_row(label: str, data: dict[str, Any], highlight: bool = False) -> None:
        nonlocal y
        vals = [label] + [str(data.get("weeks", {}).get(str(w), 0)) for w in weeks] + [str(data.get("total_points", 0)), str(data.get("avg", 0))]
        x = x0
        for i, value in enumerate(vals):
            fill = (25, 25, 15) if highlight else (8, 16, 28)
            outline = (220, 170, 30) if highlight else (42, 72, 98)
            draw.rectangle((x, y, x + widths[i], y + row_h), fill=fill, outline=outline, width=1)
            draw.text((x + 12, y + 20), value, font=_font(20 if i else 19, True), fill=(245, 245, 245))
            x += widths[i]
        y += row_h

    for model in MODEL_ORDER:
        draw_row(MODEL_SHORT[model], general["models"].get(model, {}))
    draw_row("KONSENSÜS", general["consensus"], highlight=True)

    y += 35
    draw.text((35, y), "MADDE 4 KURALI", font=_font(24, True), fill=(255, 205, 60))
    y += 45
    rule = (
        "Her Matchday yalnızca kendi maçlarıyla değerlendirilir ve raporu sabit kalır. "
        "Haftalar birbirine karıştırılmaz. Genel Performans ise 1. haftadan itibaren "
        "haftaları karşılaştırır ve sezon toplamını kümülatif olarak gösterir."
    )
    for line in _wrap(draw, rule, _font(19), width - 80):
        draw.text((35, y), line, font=_font(19), fill=(225, 225, 225))
        y += 31

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "general_performance.png"
    image.save(path)
    return path

