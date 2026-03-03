import asyncio
import logging
import time
from typing import Optional, Callable, Awaitable
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PAPER_TRADING
from core.portfolio import PortfolioManager

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, portfolio: PortfolioManager, on_approve_trade, on_reject_trade):
        self.portfolio = portfolio
        self.on_approve = on_approve_trade
        self.on_reject = on_reject_trade
        self._paused = False
        self._auto_trade = False
        self._pending_signals = {}
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self._register_handlers()

    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("trades", self._cmd_trades))
        self.app.add_handler(CommandHandler("pnl", self._cmd_pnl))
        self.app.add_handler(CommandHandler("pause", self._cmd_pause))
        self.app.add_handler(CommandHandler("resume", self._cmd_resume))
        self.app.add_handler(CommandHandler("auto", self._cmd_auto))
        self.app.add_handler(CommandHandler("manual", self._cmd_manual))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CallbackQueryHandler(self._handle_callback))

    async def start(self):
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot started")
        await self.send_message(
            f"🤖 *Polymarket Sports Bot Started*\n"
            f"Mode: {'📝 PAPER TRADING' if PAPER_TRADING else '💰 LIVE TRADING'}\n"
            f"Bankroll: ${self.portfolio.bankroll:.2f}\n\n"
            f"Use /help to see commands."
        )

    async def stop(self):
        await self.send_message("🛑 Bot shutting down.")
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    async def notify_signal(self, signal):
        if self._paused or signal.is_expired:
            return
        if self._auto_trade:
            await self.on_approve(signal)
            await self.send_message(f"⚡ *AUTO-TRADE PLACED*\n{signal.summary()}")
            return
        self._pending_signals[signal.edge.market_id] = signal
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ BUY ${signal.bet_usd}", callback_data=f"approve:{signal.edge.market_id}"),
            InlineKeyboardButton("❌ Skip", callback_data=f"reject:{signal.edge.market_id}"),
        ]])
        await self.send_message(signal.summary(), reply_markup=keyboard)

    async def _handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        action, market_id = query.data.split(":", 1)
        signal = self._pending_signals.pop(market_id, None)
        if action == "approve" and signal:
            if signal.is_expired:
                await query.edit_message_text("⏰ Signal expired.")
                return
            await self.on_approve(signal)
            await query.edit_message_text(f"✅ Trade placed: ${signal.bet_usd}")
        elif action == "reject":
            if signal:
                self.on_reject(market_id)
            await query.edit_message_text("❌ Skipped.")

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await self._cmd_help(update, ctx)

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📋 *Commands*\n\n"
            "/status — Bot status\n/pnl — Portfolio P&L\n/trades — Recent trades\n"
            "/pause — Pause bot\n/resume — Resume bot\n"
            "/auto — Auto-trade mode\n/manual — Manual approval mode",
            parse_mode=ParseMode.MARKDOWN)

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        mode = "📝 PAPER" if PAPER_TRADING else "💰 LIVE"
        trade_mode = "⚡ AUTO" if self._auto_trade else "👤 MANUAL"
        paused = "⏸ PAUSED" if self._paused else "▶️ RUNNING"
        await update.message.reply_text(
            f"*Bot Status*\n\nTrading: {mode}\nMode: {trade_mode}\nState: {paused}\nPending: {len(self._pending_signals)}",
            parse_mode=ParseMode.MARKDOWN)

    async def _cmd_pnl(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(f"*Portfolio*\n\n{self.portfolio.portfolio.summary()}", parse_mode=ParseMode.MARKDOWN)

    async def _cmd_trades(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        trades = self.portfolio.get_recent_trades(5)
        if not trades:
            await update.message.reply_text("No closed trades yet.")
            return
        lines = ["*Recent Trades*\n"]
        for t in reversed(trades):
            emoji = "✅" if (t.pnl or 0) > 0 else "❌"
            lines.append(f"{emoji} {t.question[:35]}\n   P&L: ${t.pnl:+.2f}\n")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    async def _cmd_pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._paused = True
        await update.message.reply_text("⏸ Paused. Use /resume to restart.")

    async def _cmd_resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._paused = False
        await update.message.reply_text("▶️ Resumed.")

    async def _cmd_auto(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._auto_trade = True
        await update.message.reply_text("⚡ *AUTO-TRADE MODE ON*", parse_mode=ParseMode.MARKDOWN)

    async def _cmd_manual(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._auto_trade = False
        await update.message.reply_text("👤 Manual mode on.")

    async def send_message(self, text, **kwargs):
        try:
            await self.app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode=ParseMode.MARKDOWN, **kwargs)
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
