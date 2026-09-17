from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR, SEASON_PERFORMANCE_FILE, WEEKLY_REPORTS_FILE
from performance_engine import build_season_snapshot, build_weekly_snapshot, matchday_report_due, matchday_resolution, merge_latest_results
from result_provider import FootballDataResultProvider, ResultProviderError
from source_loader import SourceLoadError, load_prediction_archive
from telegram_report import send_photo
from weekly_report import render_season_image, render_weekly_image


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _prepare_render_records(snapshot: dict, predictions: dict) -> dict:
    snapshot = dict(snapshot)
    rows = []
    for row in snapshot.get("matches", []):
        if row.get("status") != "EVALUATED":
            continue
        record = predictions.get(str(row["match_id"]))
        if record:
            rows.append(record)
    snapshot["render_records"] = rows
    return snapshot


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    weekly_reports = _load_json(WEEKLY_REPORTS_FILE, {})

    try:
        predictions = load_prediction_archive()
        provider = FootballDataResultProvider()
        by_matchday = provider.get_matches_by_matchday()
    except (SourceLoadError, ResultProviderError) as exc:
        print(f"❌ Performans botu veri hazırlığı başarısız: {exc}")
        return 1

    status_map = {str(m.get("id")): m for rows in by_matchday.values() for m in rows if m.get("id") is not None}
    graded = merge_latest_results(predictions, status_map)

    finalized_any = False
    for matchday, fixtures in sorted(by_matchday.items()):
        if not fixtures:
            continue
        key = str(matchday)
        if key not in weekly_reports and not matchday_report_due(fixtures):
            print(f"🕒 Matchday {matchday}: rapor zamanı henüz gelmedi (son planlanan başlangıç + 60 dk).")
            continue
        resolution = matchday_resolution(fixtures, graded)
        if not resolution["final"]:
            print(f"⏳ Matchday {matchday}: PENDING ({resolution['pending_matches']} maç çözülmedi).")
            continue
        if key in weekly_reports and weekly_reports[key].get("status") == "FINAL":
            # Yeni puanlama/coverage kuralları eski FINAL Matchday istatistiklerine de
            # uygulanır; eski Telegram raporu yeniden gönderilmez.
            refreshed = build_weekly_snapshot(graded, matchday, resolution)
            refreshed["finalized_at"] = weekly_reports[key].get("finalized_at", refreshed["finalized_at"])
            weekly_reports[key] = refreshed
            _save_json(WEEKLY_REPORTS_FILE, weekly_reports)
            continue

        snapshot = build_weekly_snapshot(graded, matchday, resolution)
        render_snapshot = _prepare_render_records(snapshot, graded)
        weekly_image = render_weekly_image(render_snapshot)
        weekly_reports[key] = snapshot
        _save_json(WEEKLY_REPORTS_FILE, weekly_reports)

        season = build_season_snapshot(weekly_reports)
        # Keep per-matchday points in season image data for visual weekly columns.
        for model in season["models"]:
            season["models"][model]["week_points"] = {
                str(md): int(weekly_reports[str(md)]["stats"]["models"][model]["points"])
                for md in season["finalized_matchdays"]
            }
        season["consensus"]["week_points"] = {
            str(md): int(weekly_reports[str(md)]["stats"]["consensus"]["points"])
            for md in season["finalized_matchdays"]
        }
        _save_json(SEASON_PERFORMANCE_FILE, season)
        season_image = render_season_image(season)

        send_photo(weekly_image, f"🏆 Şampiyonlar Ligi — Matchday {matchday} FINAL Performans")
        send_photo(season_image, "📊 Şampiyonlar Ligi — Sezon Genel Performans")
        finalized_any = True
        print(f"✅ Matchday {matchday} FINAL raporu hazırlandı ve gönderildi.")

    # Rebuild season file even when no new matchday finalized, so the local archive is consistent.
    season = build_season_snapshot(weekly_reports)
    for model in season["models"]:
        season["models"][model]["week_points"] = {
            str(md): int(weekly_reports[str(md)]["stats"]["models"][model]["points"])
            for md in season["finalized_matchdays"]
        }
    season["consensus"]["week_points"] = {
        str(md): int(weekly_reports[str(md)]["stats"]["consensus"]["points"])
        for md in season["finalized_matchdays"]
    }
    _save_json(SEASON_PERFORMANCE_FILE, season)

    print("🏁 Performance Bot tamamlandı.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
