"""
Technical Indicators Module

Pure pandas/numpy implementations - no TA-Lib required.
All functions take a DataFrame with OHLCV columns and return Series.
"""
import pandas as pd
import numpy as np


def calculate_rsi(df: pd.DataFrame, period: int = 14, column: str = 'close') -> pd.Series:
    """
    Relative Strength Index (RSI)

    Measures momentum by comparing recent gains to recent losses.
    Range: 0-100. Typically >70 = overbought, <30 = oversold.

    Args:
        df: DataFrame with price data.
        period: Lookback period (default 14).
        column: Price column to use.

    Returns:
        RSI values as Series.
    """
    delta = df[column].diff()

    gain = delta.where(delta > 0, 0)
    loss = (-delta.where(delta < 0, 0))

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3
) -> tuple[pd.Series, pd.Series]:
    """
    Stochastic Oscillator

    Compares closing price to price range over a period.
    %K = fast line, %D = slow line (signal).
    Range: 0-100. Typically >80 = overbought, <20 = oversold.

    Args:
        df: DataFrame with high, low, close columns.
        k_period: %K lookback period.
        d_period: %D smoothing period.

    Returns:
        Tuple of (%K, %D) Series.
    """
    low_min = df['low'].rolling(window=k_period).min()
    high_max = df['high'].rolling(window=k_period).max()

    stoch_k = 100 * (df['close'] - low_min) / (high_max - low_min)
    stoch_d = stoch_k.rolling(window=d_period).mean()

    return stoch_k, stoch_d


def calculate_bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    column: str = 'close'
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands

    Volatility bands around a moving average.
    %B shows where price is relative to bands (0 = lower, 1 = upper).

    Args:
        df: DataFrame with price data.
        period: Moving average period.
        std_dev: Standard deviation multiplier.
        column: Price column to use.

    Returns:
        Tuple of (upper, middle, lower, percent_b) Series.
    """
    middle = df[column].rolling(window=period).mean()
    std = df[column].rolling(window=period).std()

    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)

    # %B: where price is relative to bands
    # <0 = below lower, >1 = above upper
    percent_b = (df[column] - lower) / (upper - lower)

    return upper, middle, lower, percent_b


def calculate_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    column: str = 'close'
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Moving Average Convergence Divergence (MACD)

    Trend-following momentum indicator.

    Args:
        df: DataFrame with price data.
        fast: Fast EMA period.
        slow: Slow EMA period.
        signal: Signal line period.
        column: Price column to use.

    Returns:
        Tuple of (macd_line, signal_line, histogram) Series.
    """
    exp_fast = df[column].ewm(span=fast, adjust=False).mean()
    exp_slow = df[column].ewm(span=slow, adjust=False).mean()

    macd_line = exp_fast - exp_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def calculate_adx(
    df: pd.DataFrame,
    period: int = 14
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Average Directional Index (ADX)

    Measures trend strength (not direction).
    ADX > 25 = trending, ADX < 20 = ranging.
    +DI > -DI suggests uptrend, -DI > +DI suggests downtrend.

    Args:
        df: DataFrame with high, low, close columns.
        period: Lookback period.

    Returns:
        Tuple of (adx, plus_di, minus_di) Series.
    """
    high = df['high']
    low = df['low']
    close = df['close']

    # True Range
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    # Smoothed averages
    atr = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)

    # ADX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window=period).mean()

    return adx, plus_di, minus_di


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range (ATR)

    Measures volatility.

    Args:
        df: DataFrame with high, low, close columns.
        period: Lookback period.

    Returns:
        ATR values as Series.
    """
    high = df['high']
    low = df['low']
    close = df['close']

    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    return atr


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add all standard indicators to a DataFrame.

    Args:
        df: DataFrame with OHLCV columns.

    Returns:
        DataFrame with added indicator columns.
    """
    df = df.copy()

    # RSI
    df['rsi_14'] = calculate_rsi(df, 14)
    df['rsi_7'] = calculate_rsi(df, 7)

    # Stochastic
    df['stoch_k'], df['stoch_d'] = calculate_stochastic(df, 14, 3)

    # MACD
    df['macd'], df['macd_signal'], df['macd_hist'] = calculate_macd(df)

    # Bollinger Bands
    df['bb_upper'], df['bb_middle'], df['bb_lower'], df['bb_percent'] = \
        calculate_bollinger_bands(df)

    # ADX
    df['adx'], df['plus_di'], df['minus_di'] = calculate_adx(df)

    # ATR
    df['atr'] = calculate_atr(df)

    return df
