worker: python main.py
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional
from config import STARTING_BANKROLL, PAPER_TRADING

logger = logging.getLogger(__name__)
PORTFOLIO_FILE = Path("portfolio.json")

@dataclass
class Trade:
    trade_id: str
    market_id: str
    token_id: str
    question: str
    side: str
    entry_price: float
    size_usd: float
    open_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    status: str = "open"
    paper: bool = PAPER_TRADING

@dataclass
class Portfolio:
    bankroll: float = STARTING_BANKROLL
    peak_bankroll: float = STARTING_BANKROLL
    open_trades: Dict[str, Trade] = field(default_factory=dict)
    closed_trades: List[Trade] = field(default_factory=list)
    total_bets: int = 0
    total_wins: int = 0
    total_losses: int = 0

    @property
    def win_rate(self):
        settled = self.total_wins + self.total_losses
        return self.total_wins / settled if settled else 0.0

    @property
    def total_pnl(self):
        return self.bankroll - STARTING_BANKROLL

    @property
    def roi(self):
        return self.total_pnl / STARTING_BANKROLL

    @property
    def max_drawdown(self):
        if self.peak_bankroll == 0:
            return 0
        return (self.peak_bankroll - self.bankroll) / self.peak_bankroll

    def summary(self):
        mode = "📝 PAPER" if PAPER_TRADING else "💰 LIVE"
        return (
            f"{mode} Trading\n"
            f"💵 Bankroll: ${self.bankroll:.2f}\n"
            f"📈 P&L: ${self.total_pnl:+.2f} ({self.roi:+.1%})\n"
            f"🏆 Win Rate: {self.win_rate:.0%} ({self.total_wins}W / {self.total_losses}L)\n"
            f"📊 Open Positions: {len(self.open_trades)}\n"
            f"📉 Max Drawdown: {self.max_drawdown:.1%}"
        )

class PortfolioManager:
    def __init__(self):
        self.portfolio = self._load()

    def open_trade(self, trade_id, market_id, token_id, question, side, entry_price, size_usd, paper=PAPER_TRADING):
        trade = Trade(trade_id=trade_id, market_id=market_id, token_id=token_id, question=question, side=side, entry_price=entry_price, size_usd=size_usd, paper=paper)
        self.portfolio.open_trades[trade_id] = trade
        self.portfolio.bankroll -= size_usd
        self.portfolio.total_bets += 1
        self._save()
        return trade

    def close_trade(self, trade_id, exit_price):
        trade = self.portfolio.open_trades.pop(trade_id, None)
        if not trade:
            return None
        trade.exit_price = exit_price
        trade.closed_at = time.time()
        if trade.side == "YES":
            payout = trade.size_usd * (exit_price / trade.entry_price)
        else:
            payout = trade.size_usd * ((1 - exit_price) / (1 - trade.entry_price))
        trade.pnl = payout - trade.size_usd
        self.portfolio.bankroll += payout
        trade.status = "won" if trade.pnl > 0 else "lost"
        if trade.status == "won":
            self.portfolio.total_wins += 1
        else:
            self.portfolio.total_losses += 1
        if self.portfolio.bankroll > self.portfolio.peak_bankroll:
            self.portfolio.peak_bankroll = self.portfolio.bankroll
        self.portfolio.closed_trades.append(trade)
        self._save()
        return trade

    def get_open_trades(self):
        return list(self.portfolio.open_trades.values())

    def get_recent_trades(self, n=10):
        return self.portfolio.closed_trades[-n:]

    @property
    def bankroll(self):
        return self.portfolio.bankroll

    def _save(self):
        try:
            data = {
                "bankroll": self.portfolio.bankroll,
                "peak_bankroll": self.portfolio.peak_bankroll,
                "total_bets": self.portfolio.total_bets,
                "total_wins": self.portfolio.total_wins,
                "total_losses": self.portfolio.total_losses,
                "open_trades": {k: asdict(v) for k, v in self.portfolio.open_trades.items()},
                "closed_trades": [asdict(t) for t in self.portfolio.closed_trades],
            }
            PORTFOLIO_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Failed to save portfolio: {e}")

    def _load(self):
        if not PORTFOLIO_FILE.exists():
            return Portfolio()
        try:
            data = json.loads(PORTFOLIO_FILE.read_text())
            p = Portfolio(bankroll=data.get("bankroll", STARTING_BANKROLL), peak_bankroll=data.get("peak_bankroll", STARTING_BANKROLL), total_bets=data.get("total_bets", 0), total_wins=data.get("total_wins", 0), total_losses=data.get("total_losses", 0))
            for t in data.get("closed_trades", []):
                p.closed_trades.append(Trade(**t))
            for k, t in data.get("open_trades", {}).items():
                p.open_trades[k] = Trade(**t)
            return p
        except Exception as e:
            logger.error(f"Failed to load portfolio: {e}")
            return Portfolio()
