from pathlib import Path

from openpine_contracts import __version__, list_schema_ids


def test_contracts_pin_and_catalog() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert '"openpine-contracts==5.0.0rc3"' in text
    assert "openpine-contracts @ git+" not in text
    assert __version__ == "5.0.0rc3"
    assert "openpine.intent.v2" in list_schema_ids()
