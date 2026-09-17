"""Cached football data and conservative lineup verification."""
import os
import time
from datetime import datetime, timezone

import requests

from data_provider import BASE_URL, FootballDataClient, FootballDataError, APIFootballClient, FotMobClient
from learning import digest


class CachedFootball(FootballDataClient):
    def __init__(self, cache, save):
        super().__init__()
        self.cache, self.save = cache, save
        self.last_call = 0

    def _get(self, path, params=None):
        key = digest([path, params or {}])
        now = time.time()
        ttl = 240 if path.endswith('/matches') and '/competitions/' in path else 3600
        if path.startswith('/matches/'):
            ttl = 240
        entry = self.cache.get(key)
        if entry and now - entry['at'] < ttl:
            return entry['data']
        time.sleep(max(0, 6.2 - (time.monotonic() - self.last_call)))
        self.last_call = time.monotonic()
        try:
            response = requests.get(f"{BASE_URL}{path}", headers={"X-Auth-Token": self.api_key,
                "X-Unfold-Lineups": "true"}, params=params or {}, timeout=15)
            if response.status_code != 200:
                raise FootballDataError(f"football-data HTTP {response.status_code}")
            data = response.json()
            if not isinstance(data, dict):
                raise FootballDataError("football-data JSON şeması geçersiz")
        except (requests.RequestException, ValueError):
            raise FootballDataError("football-data bağlantı/JSON hatası") from None
        self.cache[key] = {'at': time.time(), 'data': data}
        # Bound cache and avoid retaining obsolete snapshots indefinitely.
        for old in list(self.cache):
            if now - self.cache[old]['at'] > 86400:
                del self.cache[old]
        self.save()
        return data

    def get_matches(self):
        year = int(os.getenv('SEASON_START', '2026'))
        return self._get('/competitions/CL/matches', {'season': year}).get('matches', [])

    def get_match_details(self, match_id):
        return self._get(f'/matches/{match_id}')

    def get_team_matches(self, team_id, before, **kwargs):
        rows = super().get_team_matches(team_id, before, **kwargs)
        return [r for r in rows if r.get('status') == 'FINISHED'
                and datetime.fromisoformat(r['utcDate'].replace('Z', '+00:00')) < before]


def valid_xi(players):
    return (isinstance(players, list) and len(players) == 11
            and all(isinstance(p, dict) and p.get('name') for p in players)
            and len({p['name'].casefold() for p in players}) == 11)


def official_xi(football, match):
    home, away = match['homeTeam']['name'], match['awayTeam']['name']
    kickoff = datetime.fromisoformat(match['utcDate'].replace('Z', '+00:00'))
    try:
        details = football.get_match_details(match['id'])
        # v4 exposes lineup under homeTeam/awayTeam, not a top-level lineups node.
        h, a = (details.get('homeTeam') or {}).get('lineup'), (details.get('awayTeam') or {}).get('lineup')
        if valid_xi(h) and valid_xi(a):
            return {'status': 'ANNOUNCED', 'home': h, 'away': a, 'source': 'football-data.org',
                    'checked_at': datetime.now(timezone.utc).isoformat()}
    except FootballDataError:
        pass
    clients = []
    if os.getenv('API_FOOTBALL_KEY'):
        clients.append(APIFootballClient)
    clients.append(FotMobClient)
    for factory in clients:
        try:
            xi = factory().get_match_official_xi(home, away, kickoff)
            if xi and valid_xi(xi.get('home')) and valid_xi(xi.get('away')):
                xi['checked_at'] = datetime.now(timezone.utc).isoformat()
                return xi
        except Exception:
            # External fallbacks must not stop the match queue or log credentials.
            pass
    return None


def predicted_xi(research):
    """Only include names accompanied by explicit eligibility checks and a source."""
    result = {'status': 'PREDICTED', 'home': [], 'away': []}
    for side in ('home', 'away'):
        players = (research.get('predicted_xi') or {}).get(side) or []
        names = set()
        for p in players if isinstance(players, list) else []:
            if not isinstance(p, dict):
                continue
            name = str(p.get('name', '')).strip()
            if (name and name.casefold() not in names and p.get('current_club_confirmed') is True
                    and p.get('unavailable') is False and str(p.get('source_url', '')).startswith('https://')):
                result[side].append(p)
                names.add(name.casefold())
        result[side] = result[side][:11]
    return result
