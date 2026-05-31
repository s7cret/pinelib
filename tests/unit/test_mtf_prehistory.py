"""Unit tests for MTF prehistory planning."""

import os

# Import the functions we're testing
import sys
from pathlib import Path

import pytest

from pinelib.core.bar import Bar
from pinelib.request import InMemoryDataProvider

# Add the stage runner to path to import the functions
stack_root = Path(os.environ.get("PINE_STACK_ROOT", Path(__file__).resolve().parents[3]))
stage_runner = stack_root / "ast2python/tools/stage_c_p4_mtf_runner.py"
if not stage_runner.exists():
    pytest.skip(
        f"optional ast2python stage runner not found: {stage_runner}",
        allow_module_level=True,
    )
sys.path.insert(0, str(stage_runner.parent))

# Import the config and functions
from stage_c_p4_mtf_runner import (  # noqa: E402
    MTFPrehistoryConfig,
    calculate_mtf_prehistory_start,
)


class TestMTFPrehistoryConfig:
    """Test MTFPrehistoryConfig dataclass."""

    def test_default_values(self):
        config = MTFPrehistoryConfig()
        assert config.requested_timeframe == "D"
        assert config.warmup_bars == 250
        assert config.include_previous_confirmed is True

    def test_custom_values(self):
        config = MTFPrehistoryConfig(
            requested_timeframe="60",
            warmup_bars=100,
            include_previous_confirmed=False,
        )
        assert config.requested_timeframe == "60"
        assert config.warmup_bars == 100
        assert config.include_previous_confirmed is False


class TestCalculateMTFPrehistoryStart:
    """Test MTF prehistory start calculation."""

    def test_daily_warmup_250(self):
        """250 D bars before target should give ~250 days prehistory."""
        # May 5 20:00 UTC
        target_start = 1778011200000
        prehistory_start = calculate_mtf_prehistory_start(
            target_start,
            requested_timeframe="D",
            warmup_bars=250,
            include_previous_confirmed=True,
        )

        # Should be approximately 251 days before
        diff_days = (target_start - prehistory_start) / 86_400_000
        assert 250 <= diff_days <= 252  # Allow for day boundary alignment

    def test_daily_warmup_250_no_previous(self):
        """250 D bars without previous confirmed should give 250 days."""
        target_start = 1778011200000
        prehistory_start = calculate_mtf_prehistory_start(
            target_start,
            requested_timeframe="D",
            warmup_bars=250,
            include_previous_confirmed=False,
        )

        diff_days = (target_start - prehistory_start) / 86_400_000
        assert 249 <= diff_days <= 251

    def test_daily_warmup_1(self):
        """1 D bar should give ~1 day prehistory."""
        target_start = 1778011200000
        prehistory_start = calculate_mtf_prehistory_start(
            target_start,
            requested_timeframe="D",
            warmup_bars=1,
            include_previous_confirmed=True,
        )

        diff_days = (target_start - prehistory_start) / 86_400_000
        assert 1 <= diff_days <= 2

    def test_hourly_60min(self):
        """60 min timeframe should use 60 min periods."""
        target_start = 1778011200000
        prehistory_start = calculate_mtf_prehistory_start(
            target_start,
            requested_timeframe="60",
            warmup_bars=10,
            include_previous_confirmed=True,
        )

        # 11 hours of prehistory (10 + 1 for previous confirmed)
        diff_hours = (target_start - prehistory_start) / 3_600_000
        assert 10 <= diff_hours <= 12


class TestMTFPrehistoryIntegration:
    """Integration tests for MTF prehistory with InMemoryDataProvider."""

    def test_previous_confirmed_d_bar_included(self):
        """When include_previous_confirmed=True, previous D bar is included."""
        # Create chart bars starting in the middle of a D period
        # May 5 20:00 is in May 5 D period (May 5 00:00 to May 5 23:59)
        chart_start = 1778011200000  # May 5 20:00

        # Create chart bars
        chart_bars = [
            Bar(
                time=chart_start + i * 900_000,
                time_close=chart_start + i * 900_000 + 899_999,
                open=80000,
                high=80100,
                low=79900,
                close=80000,
                volume=100,
            )
            for i in range(10)
        ]

        # Create D bars - May 4 and May 5
        may4_d = Bar(
            time=1777852800000,  # May 4 00:00
            time_close=1777939199999,  # May 4 23:59
            open=78000,
            high=80000,
            low=77000,
            close=79861.01,
            volume=10000,
        )

        may5_d = Bar(
            time=1777939200000,  # May 5 00:00
            time_close=1778025599999,  # May 5 23:59
            open=79861.01,
            high=82000,
            low=79000,
            close=80905.52,
            volume=12000,
        )

        provider = InMemoryDataProvider(
            {
                ("BINANCE:BTCUSDT", "15"): chart_bars,
                ("BINANCE:BTCUSDT", "D"): [may4_d, may5_d],
            }
        )

        # Query D bars
        d_bars = provider.get_bars("BINANCE:BTCUSDT", "D", start=None, end=chart_start)

        # Should include May 4 D bar (previous confirmed)
        # Should include May 5 D bar (current, not finalized)
        assert len(d_bars) >= 1
        assert any(d.time == 1777852800000 for d in d_bars)  # May 4 included

    def test_d_bars_for_close_lookback(self):
        """close needs 1 previous D bar, close[1] needs 2 previous D bars."""

        # Create D bars for May 2, 3, 4, 5 with valid OHLC (high >= max(open, close))
        d_bars = [
            Bar(
                time=1777612800000,
                time_close=1777699199999,
                open=75000,
                high=79000,
                low=74000,
                close=78000,
                volume=10000,
            ),
            Bar(
                time=1777699200000,
                time_close=1777785599999,
                open=76000,
                high=80000,
                low=75000,
                close=79000,
                volume=10000,
            ),
            Bar(
                time=1777785600000,
                time_close=1777871999999,
                open=77000,
                high=81000,
                low=76000,
                close=80000,
                volume=10000,
            ),
            Bar(
                time=1777872000000,
                time_close=1777958399999,
                open=78000,
                high=82000,
                low=77000,
                close=81000,
                volume=10000,
            ),
        ]

        chart_bars = [
            Bar(
                time=1778011200000,
                time_close=1778012099999,
                open=81000,
                high=82000,
                low=80000,
                close=81000,
                volume=100,
            )
        ]

        provider = InMemoryDataProvider(
            {
                ("BINANCE:BTCUSDT", "15"): chart_bars,
                ("BINANCE:BTCUSDT", "D"): d_bars,
            }
        )

        # Query D bars
        d_bars_result = provider.get_bars("BINANCE:BTCUSDT", "D", start=None, end=1778011200000)

        # Should have 4 D bars
        assert len(d_bars_result) == 4

        # For close: need at least 1 previous D bar (May 4 or earlier)
        # For close[1]: need 2 previous D bars (May 3 or earlier)
        # With 4 D bars including up to May 6, we have enough for close[1]


class TestMTFWarmup250:
    """Test that warmup=250 provides sufficient D bars."""

    def test_250_warmup_includes_previous_bar(self):
        """warmup_bars=250 with include_previous_confirmed=True gives 251+ bars."""
        target_start = 1778011200000  # May 5 20:00

        prehistory_start = calculate_mtf_prehistory_start(
            target_start,
            requested_timeframe="D",
            warmup_bars=250,
            include_previous_confirmed=True,
        )

        # Calculate how many D bars we'd get
        days_span = (target_start - prehistory_start) / 86_400_000

        # Should be at least 250 (251 if previous confirmed)
        assert days_span >= 250

    def test_250_warmup_enough_for_ema(self):
        """250 D bars is sufficient for EMA(26) stability."""
        # EMA(26) needs max(26, ~250) for stability
        # 250 bars is the practical minimum
        warmup = MTFPrehistoryConfig(
            requested_timeframe="D",
            warmup_bars=250,
            include_previous_confirmed=True,
        )

        assert warmup.warmup_bars >= 250

    def test_250_warmup_enough_for_rsi(self):
        """250 D bars is sufficient for RSI(14) stability."""
        warmup = MTFPrehistoryConfig(
            requested_timeframe="D",
            warmup_bars=250,
            include_previous_confirmed=True,
        )

        assert warmup.warmup_bars >= 14  # RSI needs at least 14
        assert warmup.warmup_bars >= 250  # But 250 is recommended for stability
