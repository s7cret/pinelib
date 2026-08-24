from pathlib import Path

from openpine_contracts import __version__, list_schema_ids


def test_contracts_pin_and_catalog() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert '"openpine-contracts==5.0.0rc4"' in text
    assert "openpine-contracts @ git+" not in text
    assert "a91c0ce0d36d60e8dc5cb43e7aa92ab59c2eaa6c" in ci
    assert "33b6e2a70f5442e5210de907f724739cf07c64bd" not in ci
    assert __version__ == "5.0.0rc4"
    assert "openpine.intent.v2" in list_schema_ids()
