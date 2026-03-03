import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
POLY_API_KEY        = os.getenv("POLY_API_KEY", "")
POLY_API_SECRET     = os.getenv("POLY_API_SECRET", "")
POLY_API_PASSPHRASE = os.getenv("POLY_API_PASSPHRASE", "")
POLY_WS_URL         = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
POLY_REST_URL       = "https://clob.polymarket.com"
SPORTRADAR_API_KEY  = os.getenv("SPORTRADAR_API_KEY", "")
SPORTRADAR_BASE_URL = "https://api.sportradar.us"
ACTIVE_SPORTS       = ["soccer", "basketball"]
PAPER_TRADING       = True
STARTING_BANKROLL   = 100.0
MAX_KELLY_FRACTION  = 0.06
MIN_EDGE_THRESHOLD  = 0.04
MIN_BET_USD         = 1.0
MAX_BET_USD         = 50.0
SPORTRADAR_POLL_INTERVAL = 2.0
PRICE_STALE_THRESHOLD    = 15.0
EDGE_WINDOW_SECONDS      = 8.0
LOG_LEVEL = "INFO"
LOG_FILE  = "bot.log"
