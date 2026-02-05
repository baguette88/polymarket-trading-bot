"""
Data Fetching Module

Handles price data retrieval from various sources (Binance, etc.).
Designed to be swappable - you can add new data sources easily.
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import pandas as pd

log = logging.getLogger(__name__)


class DataFetcher:
    """
    Fetches OHLCV data from external sources.

    Currently supports:
    - Binance (default for crypto)

    Easily extendable - add new methods for other sources.
    """

    BINANCE_API = "https://api.binance.com/api/v3"

    def __init__(self, default_source: str = 'binance'):
        self.default_source = default_source
        self._cache = {}
        self._cache_ttl = 30  # seconds

    def get_candles(
        self,
        symbol: str = 'BTCUSDT',
        interval: str = '15m',
        limit: int = 100,
        source: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candles.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT').
            interval: Candle interval (e.g., '15m', '1h', '4h').
            limit: Number of candles to fetch.
            source: Data source (defaults to self.default_source).

        Returns:
            DataFrame with columns: open, high, low, close, volume, timestamp
        """
        source = source or self.default_source

        if source == 'binance':
            return self._fetch_binance(symbol, interval, limit)
        else:
            raise ValueError(f"Unknown data source: {source}")

    def _fetch_binance(
        self,
        symbol: str,
        interval: str,
        limit: int
    ) -> pd.DataFrame:
        """Fetch candles from Binance API."""
        import requests

        url = f"{self.BINANCE_API}/klines"
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])

            # Convert types
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)

            # Set timestamp as index
            df.set_index('timestamp', inplace=True)

            # Keep only essential columns
            df = df[['open', 'high', 'low', 'close', 'volume']]

            log.debug(f"Fetched {len(df)} candles for {symbol} {interval}")
            return df

        except Exception as e:
            log.error(f"Binance fetch failed: {e}")
            raise

    def get_current_price(self, symbol: str = 'BTCUSDT') -> float:
        """Get current price for a symbol."""
        import requests

        url = f"{self.BINANCE_API}/ticker/price"
        params = {'symbol': symbol}

        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        return float(response.json()['price'])

    def get_candle_at_time(
        self,
        symbol: str,
        interval: str,
        timestamp: datetime
    ) -> Dict[str, float]:
        """
        Get the candle that contains a specific timestamp.
        Useful for settlement verification.

        Args:
            symbol: Trading pair.
            interval: Candle interval.
            timestamp: The time to look up.

        Returns:
            Dict with open, high, low, close, volume.
        """
        import requests

        # Convert to milliseconds
        ts_ms = int(timestamp.timestamp() * 1000)

        url = f"{self.BINANCE_API}/klines"
        params = {
            'symbol': symbol,
            'interval': interval,
            'startTime': ts_ms,
            'limit': 1
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data:
            raise ValueError(f"No candle found for {timestamp}")

        candle = data[0]
        return {
            'open': float(candle[1]),
            'high': float(candle[2]),
            'low': float(candle[3]),
            'close': float(candle[4]),
            'volume': float(candle[5])
        }
