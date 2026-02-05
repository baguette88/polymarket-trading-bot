"""
Signal Engine Module

Base class for trading signals. Subclass this to implement your strategy.
"""
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import pandas as pd

from .indicators import add_all_indicators

log = logging.getLogger(__name__)


class SignalEngine(ABC):
    """
    Abstract base class for signal generation.

    Subclass this and implement check_signal() with your strategy logic.
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Args:
            config: Strategy configuration.
        """
        self.config = config or {}
        self.last_signal = None
        self._indicators_cache = None

    def process(self, df: pd.DataFrame) -> Optional[str]:
        """
        Process price data and generate signal.

        Args:
            df: DataFrame with OHLCV data.

        Returns:
            'long', 'short', or None.
        """
        # Add indicators
        df = add_all_indicators(df)

        # Extract latest values
        indicators = self._extract_indicators(df)
        self._indicators_cache = indicators

        # Check signal
        signal = self.check_signal(indicators)

        # Handle signal reset logic
        return self._process_signal(signal)

    def _extract_indicators(self, df: pd.DataFrame) -> Dict[str, float]:
        """Extract latest indicator values from DataFrame."""
        latest = df.iloc[-1]

        return {
            'close': latest['close'],
            'rsi_14': latest.get('rsi_14'),
            'rsi_7': latest.get('rsi_7'),
            'stoch_k': latest.get('stoch_k'),
            'stoch_d': latest.get('stoch_d'),
            'macd': latest.get('macd'),
            'macd_signal': latest.get('macd_signal'),
            'macd_hist': latest.get('macd_hist'),
            'bb_percent': latest.get('bb_percent'),
            'bb_upper': latest.get('bb_upper'),
            'bb_lower': latest.get('bb_lower'),
            'adx': latest.get('adx'),
            'plus_di': latest.get('plus_di'),
            'minus_di': latest.get('minus_di'),
            'atr': latest.get('atr'),
        }

    def _process_signal(self, signal: Optional[str]) -> Optional[str]:
        """
        Handle signal state transitions.

        Requires signals to "reset" before firing again.
        This prevents repeated signals on the same condition.
        """
        if signal is None:
            # Signal cleared - reset for next time
            if self.last_signal is not None:
                log.debug(f"Signal reset (was {self.last_signal})")
                self.last_signal = None
            return None

        if signal == self.last_signal:
            # Same signal still active - don't fire again
            log.debug(f"Signal {signal} still active, waiting for reset")
            return None

        # New signal!
        log.info(f"New signal: {signal}")
        self.last_signal = signal
        return signal

    @abstractmethod
    def check_signal(self, indicators: Dict[str, float]) -> Optional[str]:
        """
        Check for trading signals based on indicators.

        THIS IS WHERE YOU IMPLEMENT YOUR STRATEGY.

        Args:
            indicators: Dict of current indicator values.

        Returns:
            'long' - bullish signal (buy YES / bet UP)
            'short' - bearish signal (buy NO / bet DOWN)
            None - no signal
        """
        pass

    @property
    def current_indicators(self) -> Optional[Dict]:
        """Get the most recent indicator values."""
        return self._indicators_cache


class ExampleMeanReversionSignal(SignalEngine):
    """
    Example implementation - simple RSI mean reversion.

    THIS IS FOR DEMONSTRATION ONLY.
    Do not use this in production without proper backtesting.
    """

    def check_signal(self, indicators: Dict[str, float]) -> Optional[str]:
        """
        Example: RSI mean reversion strategy.

        Buy when oversold (RSI < 30), sell when overbought (RSI > 70).
        """
        rsi = indicators.get('rsi_14')

        if rsi is None:
            return None

        # These thresholds are EXAMPLES ONLY
        # Real thresholds require backtesting and validation
        oversold_threshold = self.config.get('oversold', 30)
        overbought_threshold = self.config.get('overbought', 70)

        if rsi < oversold_threshold:
            return 'long'

        if rsi > overbought_threshold:
            return 'short'

        return None


class ExampleMomentumSignal(SignalEngine):
    """
    Example implementation - momentum following.

    THIS IS FOR DEMONSTRATION ONLY.
    """

    def check_signal(self, indicators: Dict[str, float]) -> Optional[str]:
        """
        Example: MACD crossover momentum strategy.
        """
        macd = indicators.get('macd')
        signal = indicators.get('macd_signal')

        if macd is None or signal is None:
            return None

        # MACD crosses above signal line
        if macd > signal and macd > 0:
            return 'long'

        # MACD crosses below signal line
        if macd < signal and macd < 0:
            return 'short'

        return None
