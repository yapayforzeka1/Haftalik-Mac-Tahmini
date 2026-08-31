import os
import json
import requests

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google import genai


# ============================================================
# AYARLAR
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
FOOTBALL_DATA_API_KEY = os.environ["FOOTBALL_DATA_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

TURKEY_TZ = ZoneInfo("Europe/Istanbul")

# Tahmin değerlendirmesi maçtan en fazla 2 saat önce başlar.
MAX_MINUTES_BEFORE = 120

# Nihai tahmin yaklaşık 50 dakika kala gönderilir.
FINAL_MINUTES_BEFORE = 50

MATCHES_FILE = Path("match_predictions.json")

GEMINI_MODEL = "gemini-3.7-flash"

FOOTBALL_API_BASE = "https://api.football-data.org/v4"

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# ============================================================
# DOSYA / KAYIT İŞLEMLERİ
# ============================================================

def load_predictions():

    if not MATCHES_FILE.exists():
        return {}

    try:

        with open(
            MATCHES_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except Exception as error:

        print(
            f"Tahmin dosyası okunamadı: {error}"
        )

        return {}


predictions = load_predictions()


def save_predictions():

    with open(
        MATCHES_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            predictions,
            file,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_message(message):

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=30
    )

    response.raise_for_status()


# ============================================================
# FOOTBALL-DATA.ORG
# ============================================================

def football_api_get(endpoint, params=None):

    url = (
        f"{FOOTBALL_API_BASE}"
        f"{endpoint}"
    )

    headers = {
        "X-Auth-Token": FOOTBALL_DATA_API_KEY
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


def get_matches():

    data = football_api_get(
        "/competitions/CL/matches"
    )

    return data.get(
        "matches",
        []
    )


def get_cl_standings():

    """
    Ücretsiz planda mevcutsa Şampiyonlar Ligi
    puan durumunu alır.

    Bazı dönemlerde sezon henüz başlamadığı için
    standings boş olabilir.
    """

    try:

        data = football_api_get(
            "/competitions/CL/standings"
        )

        standings = []

        for table in data.get(
            "standings",
            []
        ):

            for row in table.get(
                "table",
                []
            ):

                team = row.get(
                    "team",
                    {}
                )

                standings.append({
                    "team_id": team.get("id"),
                    "team": team.get("name"),
                    "position": row.get("position"),
                    "played": row.get("playedGames"),
                    "won": row.get("won"),
                    "draw": row.get("draw"),
                    "lost": row.get("lost"),
                    "points": row.get("points"),
                    "goals_for": row.get("goalsFor"),
                    "goals_against": row.get("goalsAgainst"),
                    "goal_difference": row.get(
                        "goalDifference"
                    )
                })

        return standings

    except Exception as error:

        print(
            f"Şampiyonlar Ligi puan durumu alınamadı: "
            f"{error}"
        )

        return []


def get_match_datetime(match):

    return datetime.fromisoformat(
        match["utcDate"].replace(
            "Z",
            "+00:00"
        )
    )


# ============================================================
# GEMINI VERİ HAZIRLAMA
# ============================================================

def find_team_standing(
    standings,
    team_id
):

    for row in standings:

        if row.get("team_id") == team_id:
            return row

    return None


def format_standing(
    standing
):

    if not standing:
        return "Bu takım için mevcut puan durumu verisi yok."

    return (
        f"Sıra: {standing.get('position', '-')}, "
        f"Oynanan: {standing.get('played', '-')}, "
        f"G: {standing.get('won', '-')}, "
        f"B: {standing.get('draw', '-')}, "
        f"M: {standing.get('lost', '-')}, "
        f"Puan: {standing.get('points', '-')}, "
        f"GF: {standing.get('goals_for', '-')}, "
        f"GA: {standing.get('goals_against', '-')}, "
        f"AV: {standing.get('goal_difference', '-')}"
    )


def get_prediction(
    home_team,
    away_team,
    home_standing,
    away_standing,
    minutes_until_match
):

    home_data = format_standing(
        home_standing
    )

    away_data = format_standing(
        away_standing
    )

    prompt = f"""
Sen profesyonel bir futbol skor tahmin uzmanısın.

Aşağıdaki Şampiyonlar Ligi maçı için
EN OLASI TAM MAÇ SKORUNU tahmin et.

MAÇ:

Ev sahibi:
{home_team}

Deplasman:
{away_team}

GERÇEK VERİLER:

Ev sahibi takımın mevcut Şampiyonlar Ligi verisi:
{home_data}

Deplasman takımının mevcut Şampiyonlar Ligi verisi:
{away_data}

Maça kalan süre:
{minutes_until_match:.1f} dakika

KURALLAR:

1. Öncelikle verilen gerçek verileri değerlendir.
2. Puan durumu verisi yoksa bunu uydurma.
3. Oyuncu, sakatlık, kadro veya istatistik uydurma.
4. Elinde olmayan bir bilgiyi gerçekmiş gibi kullanma.
5. Tahmini yalnızca futbol mantığına ve verilen verilere
   dayanarak oluştur.
6. Sonuç tam maç skorudur.
7. Beraberlik dahil her skor mümkündür.
8. En olası tek skoru seç.

SADECE aşağıdaki formatta cevap ver:

2-1

Başka hiçbir açıklama yazma.
"""


    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )

    return response.text.strip()


# ============================================================
# SKOR KONTROLÜ
# ============================================================

def is_valid_prediction(
    prediction
):

    try:

        parts = prediction.split("-")

        if len(parts) != 2:
            return False

        home_score = int(
            parts[0].strip()
        )

        away_score = int(
            parts[1].strip()
        )

        return (
            home_score >= 0
            and away_score >= 0
            and home_score <= 20
            and away_score <= 20
        )

    except Exception:

        return False


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    matches = get_matches()

    print(
        f"Toplam {len(matches)} "
        "Şampiyonlar Ligi maçı bulundu."
    )

    # Gerçek puan durumunu bir kez çekiyoruz.
    standings = get_cl_standings()

    print(
        f"Mevcut puan durumu kaydı: "
        f"{len(standings)} takım"
    )

    now_utc = datetime.now(
        timezone.utc
    )

    for match in matches:

        status = match.get(
            "status",
            "UNKNOWN"
        )

        # Sadece henüz başlamamış maçlar.
        if status not in (
            "SCHEDULED",
            "TIMED"
        ):
            continue

        match_id = str(
            match["id"]
        )

        home_team_data = match.get(
            "homeTeam",
            {}
        )

        away_team_data = match.get(
            "awayTeam",
            {}
        )

        home_team = home_team_data.get(
            "name",
            "Bilinmeyen takım"
        )

        away_team = away_team_data.get(
            "name",
            "Bilinmeyen takım"
        )

        home_team_id = home_team_data.get(
            "id"
        )

        away_team_id = away_team_data.get(
            "id"
        )

        match_utc = get_match_datetime(
            match
        )

        match_turkey = match_utc.astimezone(
            TURKEY_TZ
        )

        minutes_until_match = (
            match_utc - now_utc
        ).total_seconds() / 60

        print(
            f"{home_team} - {away_team} | "
            f"Türkiye: "
            f"{match_turkey.strftime('%d.%m.%Y %H:%M')} | "
            f"Kalan: "
            f"{minutes_until_match:.1f} dakika | "
            f"Durum: {status}"
        )

        # ----------------------------------------------------
        # 2 SAATTEN UZAK
        # ----------------------------------------------------

        if minutes_until_match > MAX_MINUTES_BEFORE:

            print(
                "Atlandı: Maça 2 saatten fazla var."
            )

            continue

        # ----------------------------------------------------
        # MAÇ BAŞLAMIŞ / ÇOK GEÇ
        # ----------------------------------------------------

        if minutes_until_match <= 0:

            print(
                "Atlandı: Maç başlamış veya tamamlanmış."
            )

            continue

        # ----------------------------------------------------
        # KAYIT OLUŞTUR
        # ----------------------------------------------------

        if match_id not in predictions:

            predictions[match_id] = {
                "home_team": home_team,
                "away_team": away_team,
                "match_time": match_turkey.strftime(
                    "%d.%m.%Y %H:%M"
                ),
                "last_prediction": None,
                "final_sent": False
            }

        # ----------------------------------------------------
        # PUAN DURUMU
        # ----------------------------------------------------

        home_standing = find_team_standing(
            standings,
            home_team_id
        )

        away_standing = find_team_standing(
            standings,
            away_team_id
        )

        # ----------------------------------------------------
        # GEMINI
        # ----------------------------------------------------

        print(
            f"ANALİZ EDİLİYOR: "
            f"{home_team} - {away_team}"
        )

        try:

            new_prediction = get_prediction(
                home_team,
                away_team,
                home_standing,
                away_standing,
                minutes_until_match
            )

            print(
                f"Gemini tahmini: "
                f"{new_prediction}"
            )

        except Exception as error:

            print(
                f"Gemini hatası: {error}"
            )

            continue

        # ----------------------------------------------------
        # GEÇERSİZ CEVAP
        # ----------------------------------------------------

        if not is_valid_prediction(
            new_prediction
        ):

            print(
                "Geçersiz Gemini tahmini."
            )

            continue

        previous_prediction = (
            predictions[match_id]
            .get("last_prediction")
        )

        final_sent = predictions[
            match_id
        ].get(
            "final_sent",
            False
        )

        # ----------------------------------------------------
        # 50 DAKİKA KALA SON TAHMİN
        # ----------------------------------------------------

        if (
            minutes_until_match <= FINAL_MINUTES_BEFORE
            and not final_sent
        ):

            message = (
                "🏁 MAÇ ÖNCESİ SON TAHMİN\n\n"
                f"⚽ {home_team} - {away_team}\n\n"
                f"🎯 Skor tahmini: "
                f"{new_prediction}\n\n"
                f"🇹🇷 Maç saati: "
                f"{match_turkey.strftime('%d.%m.%Y %H:%M')}"
            )

            send_telegram_message(
                message
            )

            predictions[
                match_id
            ]["last_prediction"] = (
                new_prediction
            )

            predictions[
                match_id
            ]["final_sent"] = True

            save_predictions()

            print(
                "SON TAHMİN TELEGRAM'A GÖNDERİLDİ."
            )

            continue

        # ----------------------------------------------------
        # 50 DAKİKADAN ÖNCE
        # ----------------------------------------------------

        if previous_prediction is None:

            # İlk tahmin sadece kaydedilir.
            # Telegram'a henüz gönderilmez.

            predictions[
                match_id
            ]["last_prediction"] = (
                new_prediction
            )

            save_predictions()

            print(
                "İlk tahmin kaydedildi. "
                "Telegram mesajı gönderilmedi."
            )

            continue

        # ----------------------------------------------------
        # TAHMİN DEĞİŞTİYSE
        # ----------------------------------------------------

        if (
            new_prediction != previous_prediction
        ):

            message = (
                "🔄 TAHMİN GÜNCELLENDİ\n\n"
                f"⚽ {home_team} - {away_team}\n\n"
                f"❌ Önceki: "
                f"{previous_prediction}\n\n"
                f"✅ Yeni: "
                f"{new_prediction}\n\n"
                f"🇹🇷 Maç saati: "
                f"{match_turkey.strftime('%d.%m.%Y %H:%M')}"
            )

            send_telegram_message(
                message
            )

            predictions[
                match_id
            ]["last_prediction"] = (
                new_prediction
            )

            save_predictions()

            print(
                "Tahmin değişti ve Telegram'a gönderildi."
            )

        else:

            print(
                "Tahmin değişmedi. "
                "Telegram mesajı gönderilmedi."
            )


if __name__ == "__main__":
    main()
