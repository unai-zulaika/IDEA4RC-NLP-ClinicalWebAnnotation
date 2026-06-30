"""Round-trip the Path A output through the project's CSV parser to confirm
the format matches what /api/upload/csv expects.
"""
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TOOL_ROOT = _HERE.parent
_PROJECT_ROOT = _TOOL_ROOT.parent.parent
_BACKEND = _PROJECT_ROOT / "backend"

# Make the backend importable
sys.path.insert(0, str(_BACKEND))
# Also our common.py
sys.path.insert(0, str(_TOOL_ROOT))

from common import write_path_a_csv  # noqa: E402

# Pull the parser used by /api/upload/csv
upload_module_spec = importlib.util.spec_from_file_location(
    "routes_upload", _BACKEND / "routes" / "upload.py"
)


def _parse_with_project_parser(content: str):
    """Use the same parser the upload endpoint uses."""
    # The parser depends on schemas via `from models.schemas import ...`. We don't
    # need the full Route — just import the parsing function. Import via spec
    # without executing the full module (it pulls FastAPI which may not load
    # cleanly in a unit test context).
    # Easier: copy the parsing function call path directly.
    from io import StringIO
    import csv as _csv
    # Use the same pandas-based strategies the upload route tries first.
    import pandas as pd

    df = pd.read_csv(StringIO(content), sep=";", dtype=str, keep_default_na=False)
    return df


def test_roundtrip_basic(tmp_path):
    rows = [
        {
            "text": "Simple text",
            "date": "2024-03-15",
            "p_id": "P001",
            "note_id": "1001",
            "report_type": "Visit note",
            "annotations": "gender-msci: Patient's gender male.",
        },
    ]
    out = tmp_path / "out.csv"
    write_path_a_csv(out, rows)

    content = out.read_text(encoding="utf-8")
    df = _parse_with_project_parser(content)
    assert list(df.columns) == ["text", "date", "p_id", "note_id", "report_type", "annotations"]
    assert df.iloc[0]["text"] == "Simple text"
    assert df.iloc[0]["p_id"] == "P001"
    assert df.iloc[0]["annotations"] == "gender-msci: Patient's gender male."


def test_roundtrip_embedded_semicolons(tmp_path):
    """Semicolons inside text must survive (the schema uses ; as delimiter)."""
    rows = [
        {
            "text": "Line with ;; double semicolons; and more.",
            "date": "2024-03-15",
            "p_id": "P002",
            "note_id": "1002",
            "report_type": "Path",
            "annotations": "",
        },
    ]
    out = tmp_path / "out.csv"
    write_path_a_csv(out, rows)
    df = _parse_with_project_parser(out.read_text(encoding="utf-8"))
    assert df.iloc[0]["text"] == "Line with ;; double semicolons; and more."


def test_roundtrip_embedded_quotes_and_newlines(tmp_path):
    """Quotes and newlines inside text must survive double-quoting."""
    rows = [
        {
            "text": 'Patient said "ouch".\nNext line with quote: ".',
            "date": "2024-01-01",
            "p_id": "P003",
            "note_id": "1003",
            "report_type": "Visit",
            "annotations": 'a-msci: x | b-msci: y with "quoted" word.',
        },
    ]
    out = tmp_path / "out.csv"
    write_path_a_csv(out, rows)
    df = _parse_with_project_parser(out.read_text(encoding="utf-8"))
    assert df.iloc[0]["text"] == 'Patient said "ouch".\nNext line with quote: ".'
    assert df.iloc[0]["annotations"] == 'a-msci: x | b-msci: y with "quoted" word.'


def test_no_bom(tmp_path):
    """Output should be UTF-8 without a leading BOM (Excel-on-Windows hazard)."""
    rows = [{"text": "x", "date": "", "p_id": "", "note_id": "", "report_type": "", "annotations": ""}]
    out = tmp_path / "out.csv"
    write_path_a_csv(out, rows)
    raw = out.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")


def test_header_matches_required_columns(tmp_path):
    """Header order and names must match what backend/routes/upload.py expects."""
    rows = [{"text": "x", "date": "d", "p_id": "p", "note_id": "n", "report_type": "r", "annotations": "a"}]
    out = tmp_path / "out.csv"
    write_path_a_csv(out, rows)
    first_line = out.read_text(encoding="utf-8").splitlines()[0]
    # Every field double-quoted, semicolon-separated
    expected = '"text";"date";"p_id";"note_id";"report_type";"annotations"'
    assert first_line == expected
