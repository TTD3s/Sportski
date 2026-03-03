import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from config import MIN_EDGE_THRESHOLD, MAX_KELLY_FRACTION, EDGE_WINDOW_SECONDS, PRICE_STALE_THRESHOLD
from core.sports_feed import GameState
from core.polymarket import PolymarketClient, MarketPrice
from models.probability import poisson_goal_probability, basketball_win_probability, find_edge, EdgeResult

logger = logging.getLogger(__name__)

@dataclass
class TradeSignal:
    edge: EdgeResult
    game: GameState
    market_question: str
    token_id: str
    bet_usd: float
    bankroll_at_signal: float
    detected_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + EDGE_WINDOW_SECONDS)

    @property
    def is_expired(self):
        return time.time() > self.expires_at

    def summary(self):
        return (
            f"🎯 *EDGE DETECTED*\n"
            f"Market: {self.market_question}\n"
            f"Side: {self.edge.outcome.upper()}\n"
            f"Market price: {self.edge.market_price:.1%}\n"
            f"True prob: {self.edge.true_probability:.1%}\n"
            f"Edge: +{self.edge.edge:.1%}\n"
            f"Bet size: ${self.bet_usd:.2f}\n"
            f"Confidence: {self.edge.confidence}\n"
            f"Game: {self.game.home_team} {self.game.home_score}-{self.game.away_score} {self.game.away_team} [{self.game.elapsed_seconds//60}']\n"
            f"⏰ Expires in {int(self.expires_at - time.time())}s"
        )

class EdgeDetector:
    def __init__(self, poly_client: PolymarketClient, on_signal: Callable[[TradeSignal], None], bankroll: float):
        self.poly = poly_client
        self.on_signal = on_signal
        self.bankroll = bankroll
        self._market_map: Dict[str, dict] = {}
        self._game_markets: Dict[str, List[str]] = {}
        self._recent_signals: Dict[str, float] = {}
        self._price_cache: Dict[str, MarketPrice] = {}

    def on_price_update(self, price: MarketPrice):
        self._price_cache[price.market_id] = price

    def on_game_update(self, game: GameState):
        asyncio.create_task(self._analyze_game(game))

    async def _analyze_game(self, game: GameState):
        if game.game_id not in self._game_markets:
            await self._discover_markets(game)
        market_ids = self._game_markets.get(game.game_id, [])
        if not market_ids:
            return
        probs = self._compute_probabilities(game)
        if not probs:
            return
        for market_id in market_ids:
            market_info = self._market_map.get(market_id, {})
            price = self._price_cache.get(market_id)
            if not price:
                price_val = await self.poly.get_market_price(market_id)
                if not price_val:
                    continue
            else:
                if time.time() - price.last_updated > PRICE_STALE_THRESHOLD:
                    continue
                price_val = price.yes_price
            outcome_type = market_info.get("outcome_type", "home_win")
            true_prob = probs.get(outcome_type)
            if true_prob is None:
                continue
            reasoning = f"{game.sport} | {game.home_team} {game.home_score}-{game.away_score} {game.away_team} | {game.elapsed_seconds//60}'"
            edge = find_edge(market_id=market_id, market_price=price_val, true_probability=true_prob, outcome="yes", min_edge=MIN_EDGE_THRESHOLD, max_kelly=MAX_KELLY_FRACTION, reasoning=reasoning)
            if edge:
                await self._fire_signal(edge, game, market_info)

    def _compute_probabilities(self, game: GameState):
        if game.sport == "soccer":
            elapsed_min = game.elapsed_seconds // 60
            if elapsed_min >= 90:
                return None
            return poisson_goal_probability(home_xg=max(game.home_xg, 0.5), away_xg=max(game.away_xg, 0.5), elapsed_minutes=elapsed_min, current_home_goals=game.home_score, current_away_goals=game.away_score)
        elif game.sport == "basketball":
            return basketball_win_probability(home_score=game.home_score, away_score=game.away_score, seconds_remaining=game.total_seconds - game.elapsed_seconds, possession=game.possession)
        return None

    async def _discover_markets(self, game: GameState):
        markets = await self.poly.search_sports_markets(f"{game.home_team} {game.away_team}")
        market_ids = []
        for m in markets:
            market_id = m.get("condition_id", "")
            question = m.get("question", "").lower()
            tokens = m.get("tokens", [{}])
            token_id = tokens[0].get("token_id", "") if tokens else ""
            if not market_id or not token_id:
                continue
            outcome_type = None
            if any(kw in question for kw in ["home win", f"{game.home_team.lower()} win"]):
                outcome_type = "home_win"
            elif any(kw in question for kw in ["away win", f"{game.away_team.lower()} win"]):
                outcome_type = "away_win"
            elif "draw" in question:
                outcome_type = "draw"
            elif "over 2.5" in question:
                outcome_type = "over_2_5"
            elif "both teams to score" in question:
                outcome_type = "btts"
            if outcome_type:
                self._market_map[market_id] = {"market_id": market_id, "token_id": token_id, "question": m.get("question", ""), "outcome_type": outcome_type}
                market_ids.append(market_id)
                await self.poly.subscribe_market(market_id, token_id)
        self._game_markets[game.game_id] = market_ids

    async def _fire_signal(self, edge: EdgeResult, game: GameState, market_info: dict):
        dedup_key = f"{edge.market_id}_{edge.outcome}"
        if time.time() - self._recent_signals.get(dedup_key, 0) < 60:
            return
        from config import MIN_BET_USD, MAX_BET_USD
        bet_usd = round(max(MIN_BET_USD, min(MAX_BET_USD, self.bankroll * edge.kelly_fraction)), 2)
        signal = TradeSignal(edge=edge, game=game, market_question=market_info.get("question", ""), token_id=market_info.get("token_id", ""), bet_usd=bet_usd, bankroll_at_signal=self.bankroll)
        self._recent_signals[dedup_key] = time.time()
        self.on_signal(signal)

    def update_bankroll(self, new_bankroll: float):
        self.bankroll = new_bankroll
