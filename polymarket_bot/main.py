"""
Polymarket Trading Bot - Main Entry Point

Usage:
    python -m polymarket_bot.main
    
Environment variables:
    POLYMARKET_API_KEY - Polymarket API key
    POLYMARKET_PRIVATE_KEY - Private key for signing
    CONFIG_PATH - Path to config.yaml (default: config.yaml)
    LOG_LEVEL - Logging level (default: INFO)
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from prometheus_client import start_http_server, generate_latest, CONTENT_TYPE_LATEST

from core.config import load_config
from core.state import SharedState
from data.ingestion import DataIngestionManager
from strategies.arb_engine import ArbDetector
from strategies.mispricing_engine import ExternalMispricingEngine
from strategies.micro_engine import MicrostructureEngine
from risk.manager import RiskManager
from execution.order_manager import OrderManager
from monitoring.metrics import MetricsCollector, HealthCheck
from utils.logger import setup_logging

logger = logging.getLogger(__name__)


class BotInstance:
    """Main bot instance for FastAPI app state."""
    
    def __init__(self, config):
        self.config = config
        self.state = SharedState(config.initial_capital)
        self.data_ingestion = DataIngestionManager(config, self.state)
        self.arb_engine = ArbDetector(config.fee_rate)
        self.mispricing_engine = ExternalMispricingEngine()
        self.micro_engine = MicrostructureEngine()
        self.risk_manager = RiskManager(config.risk)
        self.order_manager = OrderManager(config.api, config.paper_trading)
        self.metrics = MetricsCollector()
        self.health = HealthCheck()
        self.running = False
        self.tasks = []


async def strategy_loop(bot: BotInstance):
    """Main strategy iteration."""
    while bot.running:
        try:
            portfolio = bot.state.get_portfolio()
            books = bot.state.get_all_books()
            signals = []
            
            for market_id, book in books.items():
                # Check each strategy
                if bot.config.enable_arb:
                    if sig := check_arb(bot, market_id, book, portfolio):
                        signals.append(sig)
                
                if bot.config.enable_mispricing:
                    if sig := check_mispricing(bot, market_id, book):
                        signals.append(sig)
                
                if bot.config.enable_micro:
                    if sig := check_microstructure(bot, market_id, book):
                        signals.append(sig)
            
            # Process signals
            for signal in signals:
                await process_signal(bot, signal, portfolio)
            
            await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error(f"Strategy loop error: {e}")
            await asyncio.sleep(1)


def check_arb(bot: BotInstance, market_id: str, book, portfolio) -> dict:
    """Check arbitrage opportunities."""
    related = bot.state.get_related_markets(market_id)
    for other_id in related:
        if other_book := bot.state.get_book(other_id):
            if opp := bot.arb_engine.check(book, other_book):
                if opp.edge > bot.config.min_edge:
                    return {
                        "strategy": "ARB",
                        "market_id": opp.buy_market,
                        "side": "BUY",
                        "size": min(opp.max_size, bot.config.max_capital_per_trade),
                        "limit_price": opp.buy_price,
                        "edge": opp.edge
                    }
    return None


def check_mispricing(bot: BotInstance, market_id: str, book) -> dict:
    """Check external mispricing."""
    if signal := bot.mispricing_engine.generate_signal(market_id, book.mid_price):
        return {
            "strategy": "MISPRICING",
            "market_id": market_id,
            "side": signal.side,
            "size": signal.size * 100000,  # Convert to dollars
            "limit_price": signal.limit_price,
            "confidence": signal.confidence
        }
    return None


def check_microstructure(bot: BotInstance, market_id: str, book) -> dict:
    """Check microstructure signals."""
    if signal := bot.micro_engine.generate_signal(book):
        return {
            "strategy": "MICRO",
            "market_id": market_id,
            "side": signal.side,
            "size": signal.size * 100000,
            "limit_price": signal.limit_price,
            "confidence": signal.confidence
        }
    return None


async def process_signal(bot: BotInstance, signal: dict, portfolio):
    """Process trading signal."""
    can_trade, reason = bot.risk_manager.can_open_position(
        signal["market_id"], signal["side"], signal["size"], portfolio
    )
    
    if can_trade:
        try:
            order = await bot.order_manager.place_order(
                market_id=signal["market_id"],
                side=signal["side"],
                size=signal["size"],
                price=signal.get("limit_price")
            )
            bot.metrics.record_trade(signal["strategy"], order.status.name)
            logger.info(f"Trade: {signal['strategy']} {signal['side']} {signal['market_id']}")
        except Exception as e:
            logger.error(f"Trade failed: {e}")
            bot.metrics.record_rejected(signal["strategy"])
    else:
        bot.metrics.record_rejected(signal["strategy"])


async def risk_loop(bot: BotInstance):
    """Risk monitoring loop."""
    while bot.running:
        try:
            portfolio = bot.state.get_portfolio()
            
            # Check drawdown kill switch
            if portfolio.drawdown > bot.config.risk.kill_switch_threshold:
                logger.critical(f"KILL SWITCH: Drawdown {portfolio.drawdown:.1%}")
                await stop_bot(bot)
                break
            
            # Update metrics
            bot.metrics.update_portfolio(portfolio)
            
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Risk loop error: {e}")
            await asyncio.sleep(5)


async def start_bot(bot: BotInstance):
    """Start all bot components."""
    bot.running = True
    
    # Start data ingestion
    bot.tasks.append(asyncio.create_task(bot.data_ingestion.run()))
    
    # Start strategy loops
    bot.tasks.append(asyncio.create_task(strategy_loop(bot)))
    bot.tasks.append(asyncio.create_task(risk_loop(bot)))
    
    logger.info("Bot started")


async def stop_bot(bot: BotInstance):
    """Stop bot gracefully."""
    logger.info("Stopping bot...")
    bot.running = False
    
    for task in bot.tasks:
        task.cancel()
    
    await asyncio.gather(*bot.tasks, return_exceptions=True)
    
    # Liquidate positions
    portfolio = bot.state.get_portfolio()
    for pos in portfolio.positions.values():
        try:
            await bot.order_manager.place_order(
                market_id=pos.market_id,
                side="SELL" if pos.side.value == "BUY" else "BUY",
                size=pos.size,
                order_type="MARKET",
                timeout=5
            )
        except Exception as e:
            logger.error(f"Liquidation error: {e}")
    
    await bot.data_ingestion.stop()
    logger.info("Bot stopped")


def create_app() -> FastAPI:
    """Create FastAPI application."""
    setup_logging()
    config = load_config()
    
    app = FastAPI(title="Polymarket Trading Bot", version="1.0.0")
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.on_event("startup")
    async def startup():
        app.state.bot = BotInstance(config)
        bot = app.state.bot
        
        # Start Prometheus metrics server
        start_http_server(config.metrics_port)
        
        # Start bot
        await start_bot(bot)
    
    @app.on_event("shutdown")
    async def shutdown():
        if hasattr(app.state, "bot"):
            await stop_bot(app.state.bot)
    
    @app.get("/health")
    async def health():
        return {"status": "healthy", "running": True}
    
    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    
    @app.get("/portfolio")
    async def portfolio():
        bot = app.state.bot
        p = bot.state.get_portfolio()
        return {
            "total_value": p.total_value,
            "cash": p.cash,
            "positions": len(p.positions),
            "drawdown": p.drawdown,
            "daily_pnl": p.daily_pnl
        }
    
    @app.get("/debug")
    async def debug():
        """Debug endpoint to see bot state."""
        bot = app.state.bot
        books = bot.state.get_all_books()
        config = bot.config
        
        return {
            "config": {
                "market_ids": config.market_ids,
                "enable_arb": config.enable_arb,
                "enable_mispricing": config.enable_mispricing,
                "enable_micro": config.enable_micro,
                "paper_trading": config.paper_trading,
                "min_edge": config.min_edge
            },
            "state": {
                "active_books": len(books),
                "market_ids_with_books": list(books.keys()),
                "sample_books": {mid: {
                    "bids": len(book.bids),
                    "asks": len(book.asks),
                    "mid_price": book.mid_price,
                    "last_update": book.last_update
                } for mid, book in list(books.items())[:3]}
            }
        }
    
    @app.get("/positions")
    async def positions():
        bot = app.state.bot
        p = bot.state.get_portfolio()
        return {
            m: {
                "side": pos.side.value,
                "size": pos.size,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "pnl": pos.pnl,
                "pnl_pct": pos.pnl_pct
            }
            for m, pos in p.positions.items()
        }
    
    @app.post("/kill")
    async def kill_switch():
        """Trigger kill switch."""
        bot = app.state.bot
        await stop_bot(bot)
        return {"status": "kill_switch_triggered"}
    
    @app.post("/stop")
    async def stop():
        """Stop bot gracefully."""
        bot = app.state.bot
        await stop_bot(bot)
        return {"status": "stopped"}
    
    return app


def main():
    """Main entry point."""
    config = load_config()
    app = create_app()
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.port,
        log_level=config.log_level.lower()
    )


if __name__ == "__main__":
    main()
