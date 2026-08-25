from pathlib import Path

from openpine_contracts import __version__, list_schema_ids


def test_contracts_pin_and_catalog() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert '"openpine-contracts==5.0.0rc5"' in text
    assert "openpine-contracts @ git+" not in text
    assert "6b5e67445e2772057cd877e158c7aa0c58bdfe37" in ci
    assert "33b6e2a70f5442e5210de907f724739cf07c64bd" not in ci
    assert __version__ == "5.0.0rc5"
    assert "openpine.intent.v2" in list_schema_ids()
