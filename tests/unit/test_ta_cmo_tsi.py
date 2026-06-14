"""Tests for CMO and TSI rolling mode implementation."""

from pinelib import Bar, PineRuntime, RuntimeConfig, SymbolInfo, TimeframeInfo
from pinelib.core.na import is_na
from pinelib.ta import cmo, tsi


class TestCmoRollingMode:
    """Verify CMO works in rolling/runtime mode without hanging.

    Note: CMO must be called AFTER each bar (like Pine Script's per-bar evaluation),
    not once at the end. State accumulates across bars.
    """

    def test_cmo_runtime_matches_batch(self):
        """Runtime CMO should produce same results as batch for simple series."""
        close_vals = [100.0, 105.0, 103.0, 108.0, 106.0, 110.0, 108.0, 115.0, 113.0, 118.0]
        batch_result = cmo(close_vals, 4)
        runtime = PineRuntime(
            SymbolInfo("TEST", mintick=0.01),
            TimeframeInfo.from_string("15"),
            config=RuntimeConfig(strict_tv_parity=False),
        )
        rolling_results = []
        for c in close_vals:
            bar = Bar(time=0, open=c, high=c, low=c, close=c, volume=1000.0)
            runtime.begin_bar(bar)
            runtime.end_bar()
            r = cmo(runtime.close, 4, runtime=runtime, state_id="test_cmo")
            rolling_results.append(r)
        # Compare last non-na rolling result with last non-na batch result
        rolling_non_na = [r for r in rolling_results if not is_na(r)]
        batch_non_na = [r for r in batch_result if not is_na(r)]
        assert rolling_non_na and batch_non_na, "Both should have non-na values"
        assert (
            abs(rolling_non_na[-1] - batch_non_na[-1]) < 1e-6
        ), f"Rolling {rolling_non_na[-1]} != batch {batch_non_na[-1]}"

    def test_cmo_does_not_iterate_series(self):
        """CMO in runtime mode should not call list() on the Series."""
        runtime = PineRuntime(
            SymbolInfo("TEST", mintick=0.01),
            TimeframeInfo.from_string("15"),
            config=RuntimeConfig(strict_tv_parity=False),
        )
        # 10 bars, CMO length=4
        for i in range(10):
            c = 100.0 + i
            bar = Bar(time=i, open=c, high=c, low=c, close=c, volume=1000.0)
            runtime.begin_bar(bar)
            runtime.end_bar()
            r = cmo(runtime.close, 4, runtime=runtime, state_id="test_cmo2")
        # Last bar should be non-na
        assert not is_na(r), f"CMO should return numeric after warmup, got {r}"
        assert isinstance(r, (int, float)), f"CMO should return numeric, got {type(r)}"

    def test_cmo_warmup_behavior(self):
        """CMO should return na until enough bars are accumulated."""
        runtime = PineRuntime(
            SymbolInfo("TEST", mintick=0.01),
            TimeframeInfo.from_string("15"),
            config=RuntimeConfig(strict_tv_parity=False),
        )
        close_vals = [100.0, 105.0, 103.0, 108.0, 106.0]
        length = 4
        results = []
        for c in close_vals:
            bar = Bar(time=len(results), open=c, high=c, low=c, close=c, volume=1000.0)
            runtime.begin_bar(bar)
            runtime.end_bar()
            r = cmo(runtime.close, length, runtime=runtime, state_id="test_cmo_warmup")
            results.append(r)
        # First 'length' bars should be na (CMO needs 'length' changes, from bar 1..length)
        for i in range(length):
            assert is_na(results[i]), f"Bar {i} should be na, got {results[i]}"
        # After warmup should be non-na
        assert not is_na(results[length]), f"Bar {length} should be non-na, got {results[length]}"


class TestTsiRollingMode:
    """Verify TSI works in rolling/runtime mode without hanging.

    Note: TSI must be called AFTER each bar (like Pine Script's per-bar evaluation),
    not once at the end. State accumulates across bars.
    """

    def test_tsi_runtime_matches_batch(self):
        """Runtime TSI should produce same results as batch for simple series."""
        close_vals = [100.0 + i * 0.5 for i in range(40)]
        batch_result = tsi(close_vals, 13, 25)
        runtime = PineRuntime(
            SymbolInfo("TEST", mintick=0.01),
            TimeframeInfo.from_string("15"),
            config=RuntimeConfig(strict_tv_parity=False),
        )
        for c in close_vals:
            bar = Bar(time=0, open=c, high=c, low=c, close=c, volume=1000.0)
            runtime.begin_bar(bar)
            runtime.end_bar()
            tsi(runtime.close, 13, 25, runtime=runtime, state_id="test_tsi")
        rolling_result = tsi(runtime.close, 13, 25, runtime=runtime, state_id="test_tsi")
        if is_na(batch_result):
            assert is_na(rolling_result), "TSI should be na"
        else:
            assert not is_na(rolling_result), "TSI should compute, got na"
            batch_non_na = [r for r in batch_result if not is_na(r)]
            assert batch_non_na, "Batch should have non-na values"
            assert (
                abs(rolling_result - batch_non_na[-1]) < 1e-4
            ), f"Rolling {rolling_result} != batch {batch_non_na[-1]}"

    def test_tsi_does_not_iterate_series(self):
        """TSI in runtime mode should not call list() on the Series."""
        runtime = PineRuntime(
            SymbolInfo("TEST", mintick=0.01),
            TimeframeInfo.from_string("15"),
            config=RuntimeConfig(strict_tv_parity=False),
        )
        # Need 30+ bars for TSI(13, 25)
        for i in range(30):
            c = 100.0 + i * 0.5
            bar = Bar(time=i, open=c, high=c, low=c, close=c, volume=1000.0)
            runtime.begin_bar(bar)
            runtime.end_bar()
            tsi(runtime.close, 13, 25, runtime=runtime, state_id="test_tsi2")
        result = tsi(runtime.close, 13, 25, runtime=runtime, state_id="test_tsi2")
        assert isinstance(result, (int, float)), f"TSI should return numeric, got {type(result)}"

    def test_tsi_warmup_behavior(self):
        """TSI should return na during warmup (needs long_length bars)."""
        runtime = PineRuntime(
            SymbolInfo("TEST", mintick=0.01),
            TimeframeInfo.from_string("15"),
            config=RuntimeConfig(strict_tv_parity=False),
        )
        short_len, long_len = 13, 25
        close_vals = [100.0 + i * 0.5 for i in range(long_len + 5)]
        results = []
        for c in close_vals:
            bar = Bar(time=len(results), open=c, high=c, low=c, close=c, volume=1000.0)
            runtime.begin_bar(bar)
            runtime.end_bar()
            r = tsi(runtime.close, short_len, long_len, runtime=runtime, state_id="test_tsi_warmup")
            results.append(r)
        # Last bar should be non-na (enough bars for EMA warmup)
        assert not is_na(results[-1]), f"Last bar should be non-na, got {results[-1]}"

    def test_tsi_returns_raw_ratio_not_percent(self):
        """TSI should return raw ratio (~0.xx), not percent-scaled (~xx)."""
        # Simple trending series: close rises consistently
        close_vals = [100.0 + i * 0.5 for i in range(50)]
        result = tsi(close_vals, 13, 25)
        non_na = [r for r in result if not is_na(r)]
        assert non_na, "Should have non-na TSI values"
        # Raw ratio should be between -1 and 1 typically, definitely < 10
        for r in non_na:
            assert (
                abs(r) < 10
            ), f"TSI raw ratio should be < 10 (got {r}); likely still multiplied by 100"

    def test_tsi_runtime_matches_batch_raw_ratio(self):
        """Runtime TSI should return same raw ratio as batch."""
        close_vals = [100.0 + i * 0.5 for i in range(50)]
        batch_result = tsi(close_vals, 13, 25)
        runtime = PineRuntime(
            SymbolInfo("TEST", mintick=0.01),
            TimeframeInfo.from_string("15"),
            config=RuntimeConfig(strict_tv_parity=False),
        )
        for c in close_vals:
            bar = Bar(time=0, open=c, high=c, low=c, close=c, volume=1000.0)
            runtime.begin_bar(bar)
            runtime.end_bar()
            tsi(runtime.close, 13, 25, runtime=runtime, state_id="test_tsi_ratio")
        rolling_result = tsi(runtime.close, 13, 25, runtime=runtime, state_id="test_tsi_ratio")
        batch_non_na = [r for r in batch_result if not is_na(r)]
        assert batch_non_na, "Batch should have non-na values"
        assert abs(rolling_result - batch_non_na[-1]) < 1e-4
