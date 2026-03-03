import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable
import websockets
import httpx
from config import POLY_WS_URL, POLY_REST_URL, POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE, PAPER_TRADING

logger = logging.getLogger(__name__)

@dataclass
class MarketPrice:
    market_id: str
    token_id: str
    yes_price: float
    no_price: float
    yes_bid: float
    yes_ask: float
    spread: float
    last_updated: float = field(default_factory=time.time)
    is_stale: bool = False

@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str]
    market_id: str
    side: str
    size_usd: float
    price: float
    paper: bool
    error: Optional[str] = None

class PolymarketClient:
    def __init__(self, on_price_update: Callable[[MarketPrice], None]):
        self.on_price_update = on_price_update
        self._prices: Dict[str, MarketPrice] = {}
        self._subscribed_markets: set = set()
        self._ws = None
        self._running = False
        self._http = httpx.AsyncClient(timeout=10.0)

    async def connect(self):
        self._running = True
        while self._running:
            try:
                async with websockets.connect(POLY_WS_URL) as ws:
                    self._ws = ws
                    for market_id in self._subscribed_markets:
                        await self._subscribe(market_id)
                    async for message in ws:
                        await self._handle_message(message)
            except websockets.exceptions.ConnectionClosed:
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Polymarket WS error: {e}")
                await asyncio.sleep(5)

    async def subscribe_market(self, market_id: str, token_id: str):
        self._subscribed_markets.add(market_id)
        if self._ws:
            await self._subscribe(market_id)

    async def _subscribe(self, market_id: str):
        msg = {"type": "subscribe", "channel": "market", "market": market_id}
        await self._ws.send(json.dumps(msg))

    async def _handle_message(self, raw: str):
        try:
            data = json.loads(raw)
            msg_type = data.get("type", "")
            if msg_type == "book":
                await self._process_orderbook(data)
            elif msg_type == "price_change":
                await self._process_price_change(data)
        except Exception as e:
            logger.error(f"Error processing WS message: {e}")

    async def _process_orderbook(self, data: dict):
        market_id = data.get("market", "")
        token_id = data.get("asset_id", "")
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if not bids or not asks:
            return
        best_bid = float(bids[0]["price"]) if bids else 0.0
        best_ask = float(asks[0]["price"]) if asks else 1.0
        mid = (best_bid + best_ask) / 2
        price = MarketPrice(market_id=market_id, token_id=token_id, yes_price=mid, no_price=round(1-mid,4), yes_bid=best_bid, yes_ask=best_ask, spread=best_ask-best_bid)
        self._prices[market_id] = price
        self.on_price_update(price)

    async def _process_price_change(self, data: dict):
        market_id = data.get("market", "")
        price_val = data.get("price")
        if market_id in self._prices and price_val:
            self._prices[market_id].yes_price = float(price_val)
            self._prices[market_id].last_updated = time.time()
            self.on_price_update(self._prices[market_id])

    async def search_sports_markets(self, query: str = "soccer") -> list:
        url = f"{POLY_REST_URL}/markets"
        params = {"active": "true", "closed": "false", "tag_slug": "sports", "limit": 50}
        try:
            resp = await self._http.get(url, params=params)
            resp.raise_for_status()
            markets = resp.json().get("data", [])
            return [m for m in markets if any(kw in m.get("question","").lower() for kw in ["live","match","game","score","win"])]
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            return []

    async def get_market_price(self, market_id: str) -> Optional[float]:
        if market_id in self._prices and not self._prices[market_id].is_stale:
            return self._prices[market_id].yes_price
        try:
            url = f"{POLY_REST_URL}/last-trade-price?token_id={market_id}"
            resp = await self._http.get(url)
            return float(resp.json().get("price", 0.5))
        except Exception:
            return None

    async def place_order(self, token_id, market_id, side, price, size_usd) -> OrderResult:
        if PAPER_TRADING:
            return OrderResult(success=True, order_id=f"paper_{int(time.time())}", market_id=market_id, side=side, size_usd=size_usd, price=price, paper=True)
        try:
            headers = self._auth_headers()
            payload = {"token_id": token_id, "price": str(price), "size": str(size_usd), "side": side, "type": "LIMIT", "time_in_force": "FOK"}
            resp = await self._http.post(f"{POLY_REST_URL}/order", json=payload, headers=headers)
            resp.raise_for_status()
            return OrderResult(success=True, order_id=resp.json().get("orderID"), market_id=market_id, side=side, size_usd=size_usd, price=price, paper=False)
        except Exception as e:
            return OrderResult(success=False, order_id=None, market_id=market_id, side=side, size_usd=size_usd, price=price, paper=False, error=str(e))

    def _auth_headers(self):
        import hmac, hashlib
        ts = str(int(time.time()))
        sig = hmac.new(POLY_API_SECRET.encode(), (ts + POLY_API_KEY).encode(), hashlib.sha256).hexdigest()
        return {"POLY-API-KEY": POLY_API_KEY, "POLY-SIGNATURE": sig, "POLY-TIMESTAMP": ts, "POLY-PASSPHRASE": POLY_API_PASSPHRASE, "Content-Type": "application/json"}

    def get_cached_price(self, market_id):
        return self._prices.get(market_id)

    async def disconnect(self):
        self._running = False
        await self._http.aclose()
