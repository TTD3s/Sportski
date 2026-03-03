"""
main.py
───────
Entry point. Wires together:
  SportsRadar feed → EdgeDetector → TelegramBot
  Polymarket WS   → EdgeDetector → TelegramBot → Trade Execution
"""

import asyncio
import logging
import signal
import sys
from typing import Optional

from config import ACTIVE_SPORTS, STARTING_BANKROLL, PAPER_TRADING, LOG_LEVEL, LOG_FILE
from core.sports_feed import SportsRadarFeed, GameState
from core.polymarket import PolymarketClient
from core.edge_detector import EdgeDetector, TradeSignal
from core.portfolio import PortfolioManager
from telegram.bot import TelegramBot

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
    ],
)
logger = logging.getLogger(__name__)


class Bot:
    def __init__(self):
        self.portfolio = PortfolioManager()
        self._running = False
        self.poly_client = PolymarketClient(on_price_update=self._on_price_update)
        self.edge_detector = EdgeDetector(poly_client=self.poly_client, on_signal=self._on_signal, bankroll=self.portfolio.bankroll)
        self.sports_feed = SportsRadarFeed(on_update=self._on_game_update)
        self.telegram = TelegramBot(portfolio=self.portfolio, on_approve_trade=self._execute_trade, on_reject_trade=self._on_reject)

    def _on_price_update(self, price):
        self.edge_detector.on_price_update(price)

    def _on_game_update(self, game: GameState):
        self.edge_detector.on_game_update(game)

    def _on_signal(self, signal: TradeSignal):
        asyncio.create_task(self.telegram.notify_signal(signal))

    def _on_reject(self, market_id: str):
        logger.info(f"Signal rejected by user: {market_id}")

    async def _execute_trade(self, signal: TradeSignal):
        if signal.is_expired:
            return
        result = await self.poly_client.place_order(token_id=signal.token_id, market_id=signal.edge.market_id, side="BUY", price=signal.edge.market_price, size_usd=signal.bet_usd)
        if result.success:
            self.portfolio.open_trade(trade_id=result.order_id, market_id=result.market_id, token_id=signal.token_id, question=signal.market_question, side=signal.edge.outcome.upper(), entry_price=result.price, size_usd=result.size_usd, paper=result.paper)
            self.edge_detector.update_bankroll(self.portfolio.bankroll)
        else:
            await self.telegram.send_message(f"❌ Order failed: {result.error}")

    async def run(self):
        self._running = True
        await asyncio.gather(self.telegram.start(), self.poly_client.connect(), self.sports_feed.start(ACTIVE_SPORTS), self._heartbeat())

    async def _heartbeat(self):
        while self._running:
            await asyncio.sleep(300)

    async def shutdown(self):
        self._running = False
        await self.telegram.stop()
        await self.poly_client.disconnect()
        await self.sports_feed.stop()


async def main():
    bot = Bot()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.shutdown()))
    try:
        await bot.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        await bot.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
