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

MODEL_ICONS = {
    "Gemini 3.6 Flash": "✦",
    "Mistral Small Latest": "▣",
    "Groq Qwen 3.6 27B": "◈",
    "Cohere Command A+": "●",
    "Groq GPT-OSS 120B": "◉",
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


def _truncate(text: str, max_chars: int) -> str:
    text = str(text)
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


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
    draw.rectangle((0, 0, width, 150), fill=(8, 16, 31), outline=(35, 155, 225), width=2)
    draw.text((45, 22), title, font=_font(38, True), fill=(245, 245, 245))
    draw.text((45, 88), subtitle, font=_font(21, True), fill=(90, 210, 255))
    # Decorative trophy-like emblem without relying on external image assets.
    cx = width - 115
    draw.ellipse((cx - 42, 28, cx + 42, 110), outline=(60, 190, 255), width=3)
    draw.rectangle((cx - 23, 50, cx + 23, 90), outline=(60, 190, 255), width=3)
    draw.line((cx - 22, 90, cx + 22, 90), fill=(60, 190, 255), width=3)
    draw.line((cx, 90, cx, 122), fill=(60, 190, 255), width=3)
    draw.line((cx - 28, 122, cx + 28, 122), fill=(60, 190, 255), width=3)


def _draw_centered(draw, box, text, font, fill):
    x1, y1, x2, y2 = box
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((x1 + x2 - tw) / 2, (y1 + y2 - th) / 2 - 2), text, font=font, fill=fill)


def _draw_multiline_center(draw, box, lines: list[str], font, fill, gap=3):
    x1, y1, x2, y2 = box
    heights = []
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        heights.append(bb[3] - bb[1])
    total = sum(heights) + gap * max(0, len(lines) - 1)
    yy = (y1 + y2 - total) / 2
    for line, h in zip(lines, heights):
        bb = draw.textbbox((0, 0), line, font=font)
        tw = bb[2] - bb[0]
        draw.text(((x1 + x2 - tw) / 2, yy), line, font=font, fill=fill)
        yy += h + gap


def _kickoff_display(record: dict[str, Any]) -> str:
    value = record.get("match_time")
    if value:
        try:
            return datetime.strptime(str(value), "%d.%m.%Y %H:%M").strftime("%H:%M")
        except ValueError:
            pass
    return "--:--"


def _weekly_assessment(snapshot: dict[str, Any]) -> str:
    stats = snapshot["stats"]["models"]
    ranked = sorted(
        MODEL_ORDER,
        key=lambda model: (-int(stats[model]["points"]), -int(stats[model]["exact"]), -int(stats[model]["outcome"]), MODEL_ORDER.index(model)),
    )
    if not ranked:
        return "Bu Matchday için değerlendirilebilir AI verisi bulunmuyor."
    leader = ranked[0]
    leader_item = stats[leader]
    leader_name = MODEL_SHORT[leader]
    best_exact = max((int(stats[m]["exact"]) for m in MODEL_ORDER), default=0)
    exact_models = [MODEL_SHORT[m] for m in MODEL_ORDER if int(stats[m]["exact"]) == best_exact and best_exact > 0]
    points_text = ", ".join(f"{MODEL_SHORT[m]} {int(stats[m]['points'])} puan" for m in ranked)
    text = (
        f"Bu Matchday'de {leader_name}, {int(leader_item['points'])} puanla AI'lar arasında lider oldu. "
        f"Haftalık puan sıralaması: {points_text}. "
    )
    if exact_models:
        text += f"En çok tam skor bilen model(ler): {', '.join(exact_models)} ({best_exact} tam skor). "
    text += "Önümüzdeki Matchday'lerde bu performanslar bağımsız haftalık sonuçlar olarak korunacak ve sezon genelinde kümülatif biçimde karşılaştırılacak."
    return text


def render_weekly_image(snapshot: dict[str, Any], predictions: dict[str, Any]) -> Path:
    matchday = int(snapshot["matchday"])
    records = weekly_rows(predictions, matchday)
    width = 2100
    row_h = 96
    table_header_h = 78
    summary_h = 430
    assessment_h = 190
    height = 205 + table_header_h + max(1, len(records)) * row_h + summary_h + assessment_h
    image = Image.new("RGB", (width, height), (4, 10, 20))
    draw = ImageDraw.Draw(image)
    _draw_header(draw, image, "ŞAMPİYONLAR LİGİ 2026/27", f"HAFTALIK YAPAY ZEKA PERFORMANS RAPORU  •  MATCHDAY {matchday}")

    # Table: chronological order, with every available evaluated match.
    y = 170
    x0 = 24
    cols = [
        ("SAAT", 92),
        ("MAÇ", 270),
        ("GERÇEK\nSKOR", 105),
    ]
    for model in MODEL_ORDER:
        cols.extend([(MODEL_SHORT[model] + "\nTAHMİN", 130), ("PUAN", 82)])
    cols.extend([("KONSENSÜS\nTAHMİN", 150), ("GÜVEN", 95)])

    x_positions = []
    x = x0
    for label, w in cols:
        x_positions.append(x)
        draw.rectangle((x, y, x + w, y + table_header_h), fill=(17, 39, 67), outline=(52, 108, 155), width=2)
        lines = label.split("\n")
        _draw_multiline_center(draw, (x, y, x + w, y + table_header_h), lines, _font(14, True), (242, 246, 250), gap=1)
        x += w
    y += table_header_h

    for record in records:
        actual = record.get("actual") or {}
        actual_score = f"{actual.get('home', '-')}-{actual.get('away', '-')}"
        match_name = f"{_team_short(record['home_team'])}\n{_team_short(record['away_team'])}"
        votes = {v.get("model"): v for v in record.get("ai_votes", [])}
        consensus = record.get("consensus", {})
        successful_votes = [v for v in record.get("ai_votes", []) if v.get("success") and v.get("result")]
        successful = len(successful_votes)
        outcome_votes = int(consensus.get("outcome_votes") or 0)
        if not outcome_votes and successful:
            outcome_votes = sum(1 for v in successful_votes if v.get("result", {}).get("outcome") == consensus.get("outcome"))
        confidence = int(consensus.get("outcome_share") or 0)
        if not confidence and successful:
            confidence = int(round(outcome_votes / successful * 100))

        values: list[tuple[list[str], bool]] = [([_kickoff_display(record)], False), ([match_name], False), ([actual_score], True)]
        for model in MODEL_ORDER:
            vote = votes.get(model)
            if not vote or not vote.get("success"):
                values.extend([(["YOK"], False), (["-"], True)])
            else:
                values.extend([([str(vote.get("result", {}).get("score", "-"))], True), ([f"{_score_text(vote.get('points'))}"], True)])
        values.extend([([str(consensus.get("score", "-"))], True), ([f"%{confidence}"], True)])

        for idx, ((lines, emphasized), (_, w)) in enumerate(zip(values, cols)):
            x = x_positions[idx]
            draw.rectangle((x, y, x + w, y + row_h), fill=(7, 17, 30), outline=(38, 70, 98), width=1)
            font_size = 21 if idx == 1 else 24 if emphasized and idx == 2 else 19 if emphasized else 17
            fill = (0, 220, 255) if idx == 2 else (255, 210, 55) if (idx >= 3 and idx % 2 == 0) else (238, 241, 245)
            if idx == 0:
                fill = (235, 235, 240)
            _draw_multiline_center(draw, (x + 4, y + 3, x + w - 4, y + row_h - 3), lines, _font(font_size, True), fill, gap=2)
        y += row_h

    # Weekly ranking cards, high-to-low points as requested.
    y += 24
    draw.text((30, y), "YAPAY ZEKA HAFTALIK ÖZET PERFORMANSI", font=_font(27, True), fill=(255, 205, 55))
    y += 52
    stats = snapshot["stats"]["models"]
    ranked = sorted(
        MODEL_ORDER,
        key=lambda model: (-int(stats[model]["points"]), -int(stats[model]["exact"]), -int(stats[model]["outcome"]), MODEL_ORDER.index(model)),
    )
    card_w, card_h, gap = 325, 185, 15
    for idx, model in enumerate(ranked):
        x = 30 + idx * (card_w + gap)
        item = stats[model]
        rank = idx + 1
        medals = {1: "1", 2: "2", 3: "3", 4: "4", 5: "5"}
        draw.rectangle((x, y, x + card_w, y + card_h), fill=(10, 23, 39), outline=(55, 145, 205), width=2)
        draw.text((x + 14, y + 12), f"{medals[rank]}  {MODEL_ICONS[model]}  {MODEL_SHORT[model]}", font=_font(19, True), fill=(245, 245, 245))
        draw.text((x + 14, y + 53), f"{int(item['points'])} PUAN", font=_font(25, True), fill=(80, 220, 255))
        draw.text((x + 14, y + 92), f"Maç: {int(item['matches'])}", font=_font(15, True), fill=(225, 225, 225))
        draw.text((x + 14, y + 119), f"Sonuç: {int(item['outcome'])}   •   Tam skor: {int(item['exact'])}", font=_font(14), fill=(220, 220, 220))
        draw.text((x + 14, y + 148), f"Ortalama: {item['avg']}", font=_font(14, True), fill=(255, 210, 55))

    cons = snapshot["stats"]["consensus"]
    x = 30 + 5 * (card_w + gap)
    draw.rectangle((x, y, x + card_w, y + card_h), fill=(28, 25, 10), outline=(230, 180, 45), width=3)
    draw.text((x + 14, y + 12), "6  ★  KONSENSÜS", font=_font(18, True), fill=(255, 220, 80))
    draw.text((x + 14, y + 53), f"{int(cons['points'])} PUAN", font=_font(25, True), fill=(255, 220, 80))
    draw.text((x + 14, y + 92), f"Maç: {int(cons['matches'])}", font=_font(15, True), fill=(240, 240, 240))
    draw.text((x + 14, y + 119), f"Sonuç: {int(cons['outcome'])}   •   Tam skor: {int(cons['exact'])}", font=_font(14), fill=(225, 225, 225))
    draw.text((x + 14, y + 148), f"Ortalama: {cons['avg']}", font=_font(14, True), fill=(255, 220, 80))

    # Overall textual assessment under the table/cards.
    y += card_h + 26
    draw.rectangle((30, y, width - 30, y + assessment_h - 12), fill=(7, 17, 30), outline=(48, 110, 155), width=2)
    draw.text((48, y + 16), "HAFTALIK GENEL DEĞERLENDİRME", font=_font(24, True), fill=(115, 215, 255))
    text = _weekly_assessment(snapshot)
    yy = y + 58
    for line in _wrap(draw, text, _font(17), width - 110):
        draw.text((48, yy), line, font=_font(17), fill=(230, 233, 238))
        yy += 29

    postponed = snapshot.get("postponed_or_unavailable") or []
    if postponed:
        text = "Ertelenen/uygulanamayan: " + ", ".join(f"{p['home']} - {p['away']} ({p['status']})" for p in postponed)
        draw.text((48, y + assessment_h - 46), _truncate(text, 180), font=_font(13), fill=(255, 190, 90))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"matchday_{matchday}_weekly.png"
    image.save(path)
    return path


def _general_assessment(general: dict[str, Any], weeks: list[str]) -> str:
    ranked = sorted(
        MODEL_ORDER,
        key=lambda model: (-int(general["models"].get(model, {}).get("total_points", 0)), -int(general["models"].get(model, {}).get("exact", 0)), MODEL_ORDER.index(model)),
    )
    if not ranked:
        return "Henüz genel performans verisi bulunmuyor."
    leader = ranked[0]
    leader_data = general["models"].get(leader, {})
    ranking_text = ", ".join(f"{MODEL_SHORT[m]} {int(general['models'].get(m, {}).get('total_points', 0))}" for m in ranked)
    return (
        f"{len(weeks)} haftalık kümülatif veride lider {MODEL_SHORT[leader]} ({int(leader_data.get('total_points', 0))} puan). "
        f"Sıralama: {ranking_text}. "
        "Her haftanın puanı bağımsız bir snapshot olarak korunur; sezon toplamı haftalar ilerledikçe birikir."
    )


def render_general_image(weekly_reports: dict[str, Any]) -> Path:
    general = build_general_snapshot(weekly_reports)
    weeks = sorted({w for model in general["models"].values() for w in model["weeks"]}, key=int)
    width = 1750
    row_h = 70
    row_count = len(MODEL_ORDER) + 1
    height = 250 + row_count * row_h + 260
    image = Image.new("RGB", (width, height), (4, 10, 20))
    draw = ImageDraw.Draw(image)
    _draw_header(draw, image, "ŞAMPİYONLAR LİGİ 2026/27", "GENEL PERFORMANS  •  HAFTALAR AYRI, SEZON TOPLAMI KÜMÜLATİF")

    y = 170
    x0 = 30
    cols = ["AI MODELİ", *[f"{w}. HAFTA" for w in weeks], "SEZON TOPLAM", "ORT. PUAN"]
    widths = [300] + [130] * len(weeks) + [200, 160]
    x = x0
    for i, h in enumerate(cols):
        draw.rectangle((x, y, x + widths[i], y + 50), fill=(17, 39, 67), outline=(52, 108, 155), width=2)
        _draw_centered(draw, (x, y, x + widths[i], y + 50), h, _font(14, True), (242, 246, 250))
        x += widths[i]
    y += 50

    ranked = sorted(
        MODEL_ORDER,
        key=lambda model: (-int(general["models"].get(model, {}).get("total_points", 0)), -int(general["models"].get(model, {}).get("exact", 0)), MODEL_ORDER.index(model)),
    )

    def draw_row(label: str, data: dict[str, Any], highlight: bool = False) -> None:
        nonlocal y
        vals = [label] + [str(data.get("weeks", {}).get(str(w), 0)) for w in weeks] + [str(data.get("total_points", 0)), str(data.get("avg", 0))]
        x = x0
        for i, value in enumerate(vals):
            fill = (28, 25, 10) if highlight else (7, 17, 30)
            outline = (225, 180, 45) if highlight else (38, 70, 98)
            draw.rectangle((x, y, x + widths[i], y + row_h), fill=fill, outline=outline, width=1)
            draw.text((x + 12, y + 20), value, font=_font(19 if i else 18, True), fill=(245, 245, 245))
            x += widths[i]
        y += row_h

    for model in ranked:
        draw_row(MODEL_SHORT[model], general["models"].get(model, {}))
    draw_row("KONSENSÜS", general["consensus"], highlight=True)

    y += 30
    draw.rectangle((30, y, width - 30, height - 25), fill=(7, 17, 30), outline=(48, 110, 155), width=2)
    draw.text((50, y + 18), "GENEL SEZON DEĞERLENDİRMESİ", font=_font(23, True), fill=(255, 205, 55))
    yy = y + 60
    for line in _wrap(draw, _general_assessment(general, weeks), _font(17), width - 100):
        draw.text((50, yy), line, font=_font(17), fill=(230, 233, 238))
        yy += 29
    yy += 8
    rule = "MADDE 4: Her Matchday yalnızca kendi maçlarıyla değerlendirilir; haftalar karıştırılmaz. Genel Performans haftaları karşılaştırır ve sezon toplamını kümülatif gösterir."
    for line in _wrap(draw, rule, _font(15), width - 100):
        draw.text((50, yy), line, font=_font(15), fill=(145, 205, 240))
        yy += 25

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "general_performance.png"
    image.save(path)
    return path
