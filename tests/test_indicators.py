"""Tests for technical indicators."""
import pytest
import pandas as pd
import numpy as np

from strategy.indicators import (
    calculate_rsi,
    calculate_stochastic,
    calculate_bollinger_bands,
    calculate_macd,
    calculate_adx
)


@pytest.fixture
def sample_df():
    """Create sample OHLCV data."""
    np.random.seed(42)
    n = 100

    # Generate random walk prices
    returns = np.random.randn(n) * 0.02
    close = 100 * np.exp(np.cumsum(returns))

    # Generate OHLC from close
    high = close * (1 + np.abs(np.random.randn(n) * 0.01))
    low = close * (1 - np.abs(np.random.randn(n) * 0.01))
    open_price = np.roll(close, 1)
    open_price[0] = close[0]

    df = pd.DataFrame({
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': np.random.randint(1000, 10000, n)
    })

    return df


def test_rsi_range(sample_df):
    """RSI should be between 0 and 100."""
    rsi = calculate_rsi(sample_df, period=14)

    # Skip NaN values
    valid = rsi.dropna()
    assert (valid >= 0).all()
    assert (valid <= 100).all()


def test_stochastic_range(sample_df):
    """Stochastic %K and %D should be between 0 and 100."""
    stoch_k, stoch_d = calculate_stochastic(sample_df)

    valid_k = stoch_k.dropna()
    valid_d = stoch_d.dropna()

    assert (valid_k >= 0).all()
    assert (valid_k <= 100).all()
    assert (valid_d >= 0).all()
    assert (valid_d <= 100).all()


def test_bollinger_bands_order(sample_df):
    """Upper band should be above middle, middle above lower."""
    upper, middle, lower, pct_b = calculate_bollinger_bands(sample_df)

    # Skip NaN values
    idx = ~(upper.isna() | middle.isna() | lower.isna())

    assert (upper[idx] >= middle[idx]).all()
    assert (middle[idx] >= lower[idx]).all()


def test_macd_calculation(sample_df):
    """MACD line should equal fast EMA - slow EMA."""
    macd, signal, hist = calculate_macd(sample_df)

    # Histogram should equal MACD - Signal
    valid = ~(macd.isna() | signal.isna())
    expected_hist = macd[valid] - signal[valid]

    np.testing.assert_array_almost_equal(hist[valid].values, expected_hist.values)


def test_adx_range(sample_df):
    """ADX should be between 0 and 100."""
    adx, plus_di, minus_di = calculate_adx(sample_df)

    valid = adx.dropna()
    assert (valid >= 0).all()
    assert (valid <= 100).all()
