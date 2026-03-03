import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any
import httpx
from config import SPORTRADAR_API_KEY, SPORTRADAR_BASE_URL, SPORTRADAR_POLL_INTERVAL

logger = logging.getLogger(__name__)

@dataclass
class GameState:
    game_id: str
    sport: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    elapsed_seconds: int
    total_seconds: int
    status: str
    home_xg: float = 0.0
    away_xg: float = 0.0
    possession: Optional[str] = None
    last_event: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    fetched_at: float = field(default_factory=time.time)

class SportsRadarFeed:
    def __init__(self, on_update: Callable[[GameState], None]):
        self.on_update = on_update
        self._running = False
        self._client: Optional[httpx.AsyncClient] = None
        self._active_games: Dict[str, GameState] = {}

    async def start(self, sports: list):
        self._running = True
        self._client = httpx.AsyncClient(timeout=5.0)
        tasks = [self._poll_sport(sport) for sport in sports]
        await asyncio.gather(*tasks)

    async def stop(self):
        self._running = False
        if self._client:
            await self._client.aclose()

    async def _poll_sport(self, sport: str):
        while self._running:
            try:
                await self._fetch_live_games(sport)
            except Exception as e:
                logger.error(f"SportsRadar poll error ({sport}): {e}")
            await asyncio.sleep(SPORTRADAR_POLL_INTERVAL)

    async def _fetch_live_games(self, sport: str):
        if sport == "soccer":
            await self._fetch_soccer()
        elif sport == "basketball":
            await self._fetch_basketball()

    async def _fetch_soccer(self):
        url = f"{SPORTRADAR_BASE_URL}/soccer/trial/v4/en/schedules/live/results.json"
        params = {"api_key": SPORTRADAR_API_KEY}
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        for result in data.get("results", []):
            sport_event = result.get("sport_event", {})
            status_info = result.get("sport_event_status", {})
            game_id = sport_event.get("id", "")
            if not game_id:
                continue
            if status_info.get("match_status") not in ("live", "inprogress"):
                continue
            competitors = {c["qualifier"]: c for c in sport_event.get("competitors", [])}
            home = competitors.get("home", {})
            away = competitors.get("away", {})
            elapsed = status_info.get("clock", {}).get("played", "0'")
            elapsed_min = int(elapsed.replace("'", "").split(":")[0]) if elapsed else 0
            home_sot = float(status_info.get("home_statistics", {}).get("shots_on_target", 0) or 0)
            away_sot = float(status_info.get("away_statistics", {}).get("shots_on_target", 0) or 0)
            state = GameState(
                game_id=game_id, sport="soccer",
                home_team=home.get("name", "Home"), away_team=away.get("name", "Away"),
                home_score=status_info.get("home_score", 0), away_score=status_info.get("away_score", 0),
                elapsed_seconds=elapsed_min * 60, total_seconds=5400, status="inprogress",
                home_xg=home_sot * 0.33, away_xg=away_sot * 0.33, raw=result,
            )
            prev = self._active_games.get(game_id)
            if self._state_changed(prev, state):
                self._active_games[game_id] = state
                self.on_update(state)

    async def _fetch_basketball(self):
        url = f"{SPORTRADAR_BASE_URL}/nba/trial/v8/en/games/inseason_schedule.json"
        params = {"api_key": SPORTRADAR_API_KEY}
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        for game in data.get("games", []):
            if game.get("status") != "inprogress":
                continue
            game_id = game.get("id", "")
            home = game.get("home", {})
            away = game.get("away", {})
            quarter = game.get("quarter", 1)
            clock = game.get("clock", "12:00")
            seconds_in_quarter = self._clock_to_seconds(clock)
            total_elapsed = ((quarter - 1) * 12 * 60) + (12 * 60 - seconds_in_quarter)
            state = GameState(
                game_id=game_id, sport="basketball",
                home_team=home.get("name", "Home"), away_team=away.get("name", "Away"),
                home_score=home.get("points", 0), away_score=away.get("points", 0),
                elapsed_seconds=total_elapsed, total_seconds=2880, status="inprogress",
                possession=game.get("possession"), raw=game,
            )
            prev = self._active_games.get(game_id)
            if self._state_changed(prev, state):
                self._active_games[game_id] = state
                self.on_update(state)

    def _state_changed(self, prev, current):
        if prev is None:
            return True
        return (prev.home_score != current.home_score or prev.away_score != current.away_score or abs(prev.elapsed_seconds - current.elapsed_seconds) > 5)

    def _clock_to_seconds(self, clock):
        try:
            parts = clock.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            return 0

    @property
    def active_games(self):
        return self._active_games.copy()
