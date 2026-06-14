# PineLib 4.0.0 release checklist

Before tagging:

Coverage gate: 100% line coverage. Architecture budget: 700 lines per Python module.

1. Run the local release gate.
2. Build and smoke-test the wheel.
3. Build deterministic source zip:

```bash
python -m pinelib.distribution build-zip --root . --output pinelib-4.0.0.zip
```

4. Run cross-repo smoke in the full OpenPine workspace:

```text
pine2ast -> ast2python -> pinelib -> backtest/openpine
```

PineLib itself is dependency-light and can run hermetic tests without network access.
