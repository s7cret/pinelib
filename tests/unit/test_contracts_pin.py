from pathlib import Path

from openpine_contracts import __version__, list_schema_ids


def test_contracts_pin_and_catalog() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert '"openpine-contracts==5.0.0rc4"' in text
    assert "openpine-contracts @ git+" not in text
    assert "cd1f7c3eb8af9026ca8fa53c614586a48749419d" in ci
    assert __version__ == "5.0.0rc4"
    assert "openpine.intent.v2" in list_schema_ids()
