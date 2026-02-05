#!/usr/bin/env python3
"""
Polymarket Trading Bot - Main Orchestrator

This is the entry point that ties all modules together.
Run with: python bot.py --help
"""
import os
import sys
import json
import time
import atexit
import signal
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
log = logging.getLogger(__name__)

# Base directory
BASE_DIR = Path(__file__).parent.resolve()

# ============================================================
# SINGLETON LOCK - Prevent duplicate instances
# ============================================================

PIDFILE = BASE_DIR / "bot.pid"


def acquire_lock():
    """Ensure only one bot instance runs at a time."""
    if PIDFILE.exists():
        try:
            old_pid = int(PIDFILE.read_text().strip())
            os.kill(old_pid, 0)  # Check if process exists
            log.error(f"Bot already running (PID {old_pid})")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            pass  # Stale PID file

    PIDFILE.write_text(str(os.getpid()))
    atexit.register(release_lock)


def release_lock():
    """Clean up PID file on exit."""
    try:
        if PIDFILE.exists() and PIDFILE.read_text().strip() == str(os.getpid()):
            PIDFILE.unlink()
    except Exception:
        pass


def handle_shutdown(signum, frame):
    """Graceful shutdown handler."""
    log.info("Shutdown signal received")
    release_lock()
    sys.exit(0)


# ============================================================
# BOT CLASS
# ============================================================

class TradingBot:
    """
    Main trading bot orchestrator.

    Coordinates:
    - Data fetching
    - Signal generation
    - Order execution
    - State management
    - Risk checks
    """

    def __init__(self, config_path: str = 'config/bot_config.json', paper: bool = False):
        """
        Initialize the bot.

        Args:
            config_path: Path to configuration file.
            paper: Run in paper trading mode (no real orders).
        """
        self.paper_mode = paper
        self.config = self._load_config(config_path)
        self.running = False

        # Initialize components
        self._init_components()

        log.info(f"Bot initialized (paper={paper})")

    def _load_config(self, path: str) -> dict:
        """Load configuration from JSON file."""
        config_file = BASE_DIR / path
        if config_file.exists():
            with open(config_file) as f:
                return json.load(f)

        # Default config
        return {
            'interval_seconds': 60,
            'symbol': 'BTCUSDT',
            'candle_interval': '15m',
            'candle_limit': 100,
            'base_bet': 5.0,
            'max_entry_price': 0.60,
            'max_spread': 0.10
        }

    def _init_components(self):
        """Initialize all bot components."""
        from core import PolymarketClient, DataFetcher, OrderExecutor, StateManager, RiskManager
        from strategy.signals import ExampleMeanReversionSignal

        # Data fetcher
        self.data = DataFetcher()

        # State manager
        self.state = StateManager(state_file=str(BASE_DIR / 'state.json'))

        # Risk manager
        self.risk = RiskManager(self.config, self.state)

        # Signal engine - REPLACE THIS WITH YOUR STRATEGY
        self.signals = ExampleMeanReversionSignal(self.config)

        # Polymarket client and executor (only if not paper mode)
        if not self.paper_mode:
            self.client = PolymarketClient()
            if not self.client.connect():
                raise RuntimeError("Failed to connect to Polymarket")
            self.executor = OrderExecutor(self.client, self.config)
        else:
            self.client = None
            self.executor = None
            log.info("Paper trading mode - no real orders will be placed")

    def run(self):
        """Main bot loop."""
        self.running = True
        interval = self.config.get('interval_seconds', 60)

        log.info(f"Starting bot loop (interval={interval}s)")

        while self.running:
            try:
                self._cycle()
            except KeyboardInterrupt:
                log.info("Keyboard interrupt")
                break
            except Exception as e:
                log.error(f"Cycle error: {e}", exc_info=True)

            # Update heartbeat
            self._heartbeat()

            # Sleep until next cycle
            time.sleep(interval)

        log.info("Bot stopped")

    def _cycle(self):
        """Single trading cycle."""
        log.debug("Starting cycle")

        # 1. Check kill switch
        if not self.risk.check_kill_switch():
            log.warning("Kill switch triggered - skipping cycle")
            return

        # 2. Fetch data
        symbol = self.config.get('symbol', 'BTCUSDT')
        interval = self.config.get('candle_interval', '15m')
        limit = self.config.get('candle_limit', 100)

        df = self.data.get_candles(symbol, interval, limit)

        # 3. Check for signals
        signal = self.signals.process(df)

        if signal:
            self._handle_signal(signal)

        # 4. Check pending resolutions
        self._check_resolutions()

        log.debug("Cycle complete")

    def _handle_signal(self, signal: str):
        """Handle a trading signal."""
        log.info(f"Signal received: {signal}")

        # Get market to trade
        # NOTE: You need to implement market discovery for your use case
        # This is a placeholder
        market = self._get_target_market()

        if not market:
            log.warning("No target market found")
            return

        # Check if we already traded this market
        if self.state.already_traded_market(market['condition_id']):
            log.info("Already traded this market, skipping")
            return

        # Determine which token to buy
        if signal == 'long':
            token_id = market['yes_token_id']
            outcome = 'YES'
        else:
            token_id = market['no_token_id']
            outcome = 'NO'

        # Paper mode - just log
        if self.paper_mode:
            log.info(f"PAPER TRADE: {signal} on {market['slug']} ({outcome})")
            return

        # Get orderbook and check risk
        book = self.client.get_orderbook(token_id)
        allowed, reason = self.risk.check_entry_allowed(book)

        if not allowed:
            log.warning(f"Entry blocked: {reason}")
            return

        # Calculate position size
        size = self.risk.get_position_size(
            entry_price=book['ask'],
            direction=signal
        )

        # Execute
        result = self.executor.execute_buy(token_id, size, self.config.get('max_entry_price'))

        if result.success:
            # Record trade
            from core.state import Trade
            trade = Trade.create(
                market_id=market['condition_id'],
                token_id=token_id,
                direction=signal,
                outcome=outcome,
                entry_price=result.filled_price,
                size=result.filled_size,
                amount_usd=size,
                order_id=result.order_id,
                tx_hash=result.tx_hash
            )
            self.state.add_trade(trade)
            log.info(f"Trade executed: {trade.id}")
        else:
            log.error(f"Trade failed: {result.error}")

    def _get_target_market(self) -> dict:
        """
        Get the market to trade.

        YOU MUST IMPLEMENT THIS for your specific use case.
        This could search for BTC price markets, specific events, etc.
        """
        # Placeholder - implement market discovery
        return None

    def _check_resolutions(self):
        """Check for and process trade resolutions."""
        unresolved = self.state.get_unresolved_trades()

        for trade in unresolved:
            try:
                # Check if market resolved
                # YOU MUST IMPLEMENT resolution logic for your markets
                pass
            except Exception as e:
                log.warning(f"Resolution check failed for {trade['id']}: {e}")

    def _heartbeat(self):
        """Update heartbeat file for monitoring."""
        heartbeat_file = BASE_DIR / '.heartbeat'
        heartbeat_file.write_text(datetime.now(timezone.utc).isoformat())

    def stop(self):
        """Stop the bot."""
        self.running = False


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Polymarket Trading Bot')
    parser.add_argument('--paper', action='store_true', help='Paper trading mode')
    parser.add_argument('--config', default='config/bot_config.json', help='Config file path')
    parser.add_argument('--interval', type=int, help='Override cycle interval (seconds)')
    parser.add_argument('--once', action='store_true', help='Run single cycle and exit')

    args = parser.parse_args()

    # Setup signal handlers
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # Acquire lock
    acquire_lock()

    # Initialize bot
    bot = TradingBot(config_path=args.config, paper=args.paper)

    if args.interval:
        bot.config['interval_seconds'] = args.interval

    if args.once:
        bot._cycle()
    else:
        bot.run()


if __name__ == '__main__':
    main()
