"""
Risk Management Module

Handles position sizing, loss limits, and kill switches.
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)


class KillSwitchTriggered(Exception):
    """Raised when a kill switch condition is met."""
    pass


class RiskManager:
    """
    Manages trading risk parameters.

    Features:
    - Position sizing (fixed, percent, Kelly)
    - Daily/total loss limits
    - Maximum open positions
    - Consecutive loss handling
    - Kill switch logic
    """

    def __init__(self, config: Dict[str, Any], state_manager=None):
        """
        Args:
            config: Risk configuration dict.
            state_manager: StateManager instance for P&L tracking.
        """
        self.config = config
        self.state = state_manager

        # Position sizing
        self.base_bet = config.get('base_bet', 5.0)
        self.min_bet = config.get('min_bet', 3.0)
        self.max_bet = config.get('max_bet', 50.0)
        self.sizing_mode = config.get('sizing_mode', 'fixed')

        # Limits
        self.max_daily_loss = config.get('max_daily_loss', 100.0)
        self.max_total_loss = config.get('max_total_loss', 500.0)
        self.max_open_positions = config.get('max_open_positions', 3)
        self.max_consecutive_losses = config.get('max_consecutive_losses', 5)

        # Entry constraints
        self.max_entry_price = config.get('max_entry_price', 0.60)
        self.min_spread = config.get('min_spread', 0.01)
        self.max_spread = config.get('max_spread', 0.10)

        # Tracking
        self._consecutive_losses = 0

    def get_position_size(
        self,
        entry_price: float,
        direction: str = 'long',
        strategy: str = 'default',
        bankroll: Optional[float] = None
    ) -> float:
        """
        Calculate position size based on configured method.

        Args:
            entry_price: Expected entry price (0-1).
            direction: Trade direction.
            strategy: Strategy identifier (for strategy-specific sizing).
            bankroll: Current bankroll (needed for percent/Kelly modes).

        Returns:
            Dollar amount to bet.
        """
        if self.sizing_mode == 'fixed':
            size = self._fixed_size(entry_price)

        elif self.sizing_mode == 'percent' and bankroll:
            size = self._percent_size(bankroll)

        elif self.sizing_mode == 'kelly' and bankroll:
            win_rate = self.config.get('win_rates', {}).get(
                f"{strategy}_{direction}",
                self.config.get('default_win_rate', 0.55)
            )
            size = self._kelly_size(bankroll, win_rate, entry_price)

        else:
            size = self.base_bet

        # Apply limits
        size = max(self.min_bet, min(self.max_bet, size))

        # Reduce after consecutive losses
        if self._consecutive_losses >= 3:
            reduction = 0.5 ** (self._consecutive_losses - 2)
            size *= reduction
            log.warning(f"Reduced size to {size:.2f} after {self._consecutive_losses} losses")

        return round(size, 2)

    def _fixed_size(self, entry_price: float) -> float:
        """Fixed bet with optional price-based adjustment."""
        # Lean into cheap entries (more asymmetry)
        if entry_price < 0.40:
            return self.base_bet * 1.5
        elif entry_price < 0.50:
            return self.base_bet
        elif entry_price < 0.55:
            return self.base_bet * 0.75
        else:
            return self.base_bet * 0.5

    def _percent_size(self, bankroll: float) -> float:
        """Fixed percentage of bankroll."""
        percent = self.config.get('bankroll_percent', 0.02)
        return bankroll * percent

    def _kelly_size(
        self,
        bankroll: float,
        win_rate: float,
        entry_price: float,
        fraction: float = 0.5
    ) -> float:
        """
        Half-Kelly criterion for binary markets.

        Kelly: f* = (bp - q) / b
        where b = odds, p = win prob, q = 1-p
        """
        if win_rate <= 0.5 or entry_price <= 0 or entry_price >= 1:
            return self.min_bet

        # Net odds for binary market
        b = (1.0 - entry_price) / entry_price
        p = win_rate
        q = 1 - p

        kelly_full = (b * p - q) / b

        if kelly_full <= 0:
            return self.min_bet

        kelly_fraction = kelly_full * fraction
        bet = kelly_fraction * bankroll

        # Cap at 10% of bankroll regardless
        max_bankroll_bet = bankroll * 0.10
        return min(bet, max_bankroll_bet)

    def check_entry_allowed(self, orderbook: Dict) -> tuple[bool, str]:
        """
        Check if trade entry is allowed based on market conditions.

        Args:
            orderbook: Orderbook data with 'ask', 'bid', 'spread'.

        Returns:
            (allowed, reason) tuple.
        """
        # Price check
        if orderbook['ask'] > self.max_entry_price:
            return False, f"Ask {orderbook['ask']:.2f} > max {self.max_entry_price}"

        # Spread check
        if orderbook['spread'] > self.max_spread:
            return False, f"Spread {orderbook['spread']:.2%} > max {self.max_spread:.2%}"

        if orderbook['spread'] < self.min_spread:
            return False, f"Spread {orderbook['spread']:.2%} < min (suspicious)"

        return True, "OK"

    def check_kill_switch(self) -> bool:
        """
        Check if kill switch should be triggered.

        Returns:
            True if trading should continue, False if should stop.

        Raises:
            KillSwitchTriggered: If a hard limit is exceeded.
        """
        if not self.state:
            return True

        # Total loss limit
        if self.state.pnl < -self.max_total_loss:
            raise KillSwitchTriggered(
                f"Total loss limit exceeded: ${self.state.pnl:.2f}"
            )

        # Daily loss limit
        daily_pnl = self._calculate_daily_pnl()
        if daily_pnl < -self.max_daily_loss:
            raise KillSwitchTriggered(
                f"Daily loss limit exceeded: ${daily_pnl:.2f}"
            )

        # Consecutive losses
        if self._consecutive_losses >= self.max_consecutive_losses:
            log.warning(f"Consecutive losses: {self._consecutive_losses}")
            # Don't kill, but return False to pause
            return False

        # Open position limit
        open_positions = len(self.state.get_unresolved_trades())
        if open_positions >= self.max_open_positions:
            log.info(f"Max open positions reached: {open_positions}")
            return False

        return True

    def _calculate_daily_pnl(self) -> float:
        """Calculate P&L for today only."""
        if not self.state:
            return 0

        today = datetime.now(timezone.utc).date()
        daily_pnl = 0

        for trade in self.state._state.get('trades', []):
            if not trade.get('resolved'):
                continue

            trade_date = datetime.fromisoformat(
                trade['timestamp'].replace('Z', '+00:00')
            ).date()

            if trade_date == today:
                daily_pnl += trade.get('pnl', 0)

        return daily_pnl

    def record_result(self, result: str):
        """
        Record trade result for consecutive loss tracking.

        Args:
            result: 'win' or 'loss'.
        """
        if result == 'loss':
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0
