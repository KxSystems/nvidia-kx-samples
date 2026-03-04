"""Generate synthetic OHLCV + order book data for KDB-X financial analytics demo.

Model
-----
Geometric Brownian Motion with Ornstein-Uhlenbeck mean reversion.
Produces deterministic output (seed 42) for reproducibility.

Output
------
``data/sample_market_data.parquet`` -- ~2.5 M rows across 5 tickers.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SEED = 42
TICKERS: dict[str, dict[str, float]] = {
    "AAPL": {"base_price": 175.0, "annual_vol": 0.25},
    "NVDA": {"base_price": 500.0, "annual_vol": 0.35},
    "MSFT": {"base_price": 380.0, "annual_vol": 0.22},
    "GOOG": {"base_price": 140.0, "annual_vol": 0.28},
    "AMZN": {"base_price": 155.0, "annual_vol": 0.30},
}

TRADING_DAYS = 252  # 2025-01-02 to 2025-12-31
MARKET_OPEN_MINUTES = 390  # 09:30 - 16:00 ET
KAPPA = 0.001  # OU mean-reversion speed per minute
TICK_SIZE = 0.01

OUTPUT_DIR = pathlib.Path(__file__).resolve().parent
OUTPUT_FILE = OUTPUT_DIR / "sample_market_data.parquet"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trading_dates() -> pd.DatetimeIndex:
    """Return 252 NYSE trading days in 2025."""
    all_days = pd.bdate_range("2025-01-02", periods=TRADING_DAYS, freq="B")
    return all_days


def _intraday_timestamps(date: pd.Timestamp) -> pd.DatetimeIndex:
    """Return 1-minute bar timestamps from 09:30 to 15:59 for *date*."""
    start = date + pd.Timedelta(hours=9, minutes=30)
    return pd.date_range(start, periods=MARKET_OPEN_MINUTES, freq="min")


def _u_shape(n: int) -> np.ndarray:
    """U-shaped volume profile (high at open and close)."""
    x = np.linspace(-1, 1, n)
    curve = 1.0 + 2.0 * x**2
    return curve / curve.sum()


# ---------------------------------------------------------------------------
# Per-ticker data generation
# ---------------------------------------------------------------------------


def _generate_ticker(
    sym: str,
    base_price: float,
    annual_vol: float,
    dates: pd.DatetimeIndex,
    rng: np.random.RandomState,
) -> pd.DataFrame:
    """Generate 1-minute bars for a single ticker across all trading days."""
    dt = 1.0 / (MARKET_OPEN_MINUTES * TRADING_DAYS)  # fraction of year per bar
    sigma = annual_vol
    vol_per_bar = sigma * np.sqrt(dt)

    rows: list[dict] = []
    prev_close = base_price

    for date in dates:
        timestamps = _intraday_timestamps(date)
        n = len(timestamps)

        # Intraday noise for OU mean-reversion
        noise = rng.standard_normal(n)
        volume_profile = _u_shape(n)
        base_volume = rng.randint(800_000, 1_500_000)

        for i, ts in enumerate(timestamps):
            # OU + GBM step
            drift = KAPPA * (base_price - prev_close)
            close = prev_close * np.exp(
                (drift / prev_close - 0.5 * vol_per_bar**2) + vol_per_bar * noise[i]
            )
            close = round(close, 2)

            # Bar construction
            intraday_vol = abs(noise[i]) * vol_per_bar * prev_close
            high = round(close + abs(rng.normal(0, 1)) * intraday_vol + TICK_SIZE, 2)
            low = round(close - abs(rng.normal(0, 1)) * intraday_vol - TICK_SIZE, 2)
            low = max(low, TICK_SIZE)  # no negative prices
            if low > close:
                low = round(close - TICK_SIZE, 2)
            if high < close:
                high = round(close + TICK_SIZE, 2)

            gap = rng.normal(0, vol_per_bar * prev_close * 0.1)
            open_price = round(prev_close + gap, 2)
            open_price = max(open_price, TICK_SIZE)

            # Ensure OHLC consistency
            high = max(high, open_price, close)
            low = min(low, open_price, close)

            volume = max(int(base_volume * volume_profile[i] + rng.normal(0, 50)), 1)
            vwap = round((high + low + close) / 3, 4)
            trade_count = max(int(volume / rng.uniform(80, 200)), 1)

            # Order book
            spread = round(TICK_SIZE * (1 + abs(rng.lognormal(0, 0.3))), 4)
            bid_price = round(close - spread / 2, 2)
            ask_price = round(close + spread / 2, 2)
            bid_size = max(int(rng.exponential(500)), 100)
            ask_size = max(int(rng.exponential(500)), 100)
            mid = round((bid_price + ask_price) / 2, 4)

            rows.append(
                {
                    "sym": sym,
                    "timestamp": ts,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "vwap": vwap,
                    "trade_count": trade_count,
                    "bid_price": bid_price,
                    "bid_size": bid_size,
                    "ask_price": ask_price,
                    "ask_size": ask_size,
                    "mid": mid,
                    "spread": spread,
                }
            )
            prev_close = close

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def generate() -> pd.DataFrame:
    """Generate the full synthetic dataset and return as DataFrame."""
    rng = np.random.RandomState(SEED)
    dates = _trading_dates()
    frames: list[pd.DataFrame] = []

    for sym, cfg in TICKERS.items():
        print(f"Generating {sym} ({TRADING_DAYS} days x {MARKET_OPEN_MINUTES} bars)...")
        df = _generate_ticker(sym, cfg["base_price"], cfg["annual_vol"], dates, rng)
        frames.append(df)

    full = pd.concat(frames, ignore_index=True)
    full["sym"] = full["sym"].astype("category")
    full["timestamp"] = pd.to_datetime(full["timestamp"])
    return full


def main() -> None:
    df = generate()
    df.to_parquet(OUTPUT_FILE, index=False, engine="pyarrow")
    print(f"Wrote {len(df):,} rows to {OUTPUT_FILE}")
    print(f"Tickers: {sorted(df['sym'].unique())}")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"File size: {OUTPUT_FILE.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
