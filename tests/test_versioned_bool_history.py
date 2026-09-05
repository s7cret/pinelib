import pytest
from pinelib import CallbackFrame, RuntimeLanguageContext, RuntimeSession, na
from pinelib.errors import PineRuntimeError


@pytest.mark.parametrize("version", range(1, 7))
def test_missing_bool_history_preserves_version_semantics(version):
    session = RuntimeSession(
        RuntimeLanguageContext(
            version,
            "2026-09-01",
            f"pine-v{version}",
            "sha256:" + "1" * 64,
            "compiler_annotation",
        )
    )
    tx = session.begin(CallbackFrame("HISTORICAL_EVAL", 0))
    tx.set_series("flag", True, "bool")
    tx.set_series("number", 1.0, "float")
    expected = False if version == 6 else na
    assert tx.op_series_history("flag", 1) is expected
    assert tx.op_series_history(session.series["flag"], 1) is expected
    assert tx.op_series_history("number", 1) is na
    tx.commit()
    tx = session.begin(CallbackFrame("HISTORICAL_EVAL", 1))
    tx.set_series("flag", False, "bool")
    assert tx.op_series_history("flag", 1) is True
    assert tx.op_series_history("flag", 2) is expected
    assert tx.op_series_history("flag", 0) is False
    with pytest.raises(PineRuntimeError):
        tx.op_series_history("flag", -1)
    with pytest.raises(PineRuntimeError):
        tx.op_series_history("flag", True)
    tx.abort()
