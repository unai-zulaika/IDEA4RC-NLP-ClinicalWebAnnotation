"""Tests for flexible CSV parsing in upload route."""

import pytest
from fastapi import HTTPException
from routes.upload import (
    _parse_csv_flexible,
    _parse_csv_with_reconstruction,
    _decode_csv_bytes,
)


REQUIRED_COLS = ['text', 'date', 'p_id', 'note_id', 'report_type']
FEWSHOT_COLS = ['prompt_type', 'note_text', 'annotation']


def test_standard_semicolon_csv():
    data = "text;date;p_id;note_id;report_type\nhello;2024-01-01;1;100;CCE\n"
    df = _parse_csv_flexible(data, REQUIRED_COLS)
    assert list(df.columns) == REQUIRED_COLS
    assert len(df) == 1
    assert df.iloc[0]['text'] == 'hello'


def test_broken_quoting_semicolon_csv():
    """Reproduces the bug: entire row wrapped in quotes with escaped inner quotes."""
    data = (
        '"text;""date"";""p_id"";""note_id"";""report_type"""\n'
        '"some text;""2024-01-01"";""1"";""100"";""CCE"""\n'
    )
    df = _parse_csv_flexible(data, REQUIRED_COLS)
    assert 'text' in df.columns
    assert 'date' in df.columns
    assert len(df) == 1
    assert df.iloc[0]['p_id'] == '1'


def test_comma_delimited_csv():
    data = "text,date,p_id,note_id,report_type\nhello,2024-01-01,1,100,CCE\n"
    df = _parse_csv_flexible(data, REQUIRED_COLS)
    assert list(df.columns) == REQUIRED_COLS
    assert df.iloc[0]['text'] == 'hello'


def test_tab_delimited_csv():
    data = "text\tdate\tp_id\tnote_id\treport_type\nhello\t2024-01-01\t1\t100\tCCE\n"
    df = _parse_csv_flexible(data, REQUIRED_COLS)
    assert list(df.columns) == REQUIRED_COLS
    assert df.iloc[0]['text'] == 'hello'


def test_missing_required_columns_raises():
    data = "col_a;col_b\nval1;val2\n"
    with pytest.raises(HTTPException) as exc_info:
        _parse_csv_flexible(data, REQUIRED_COLS)
    assert exc_info.value.status_code == 400
    assert "required columns" in exc_info.value.detail.lower()


def test_whitespace_in_column_names():
    data = " text ; date ; p_id ; note_id ; report_type \nhello;2024-01-01;1;100;CCE\n"
    df = _parse_csv_flexible(data, REQUIRED_COLS)
    assert 'text' in df.columns
    assert 'report_type' in df.columns


def test_fewshot_csv_columns():
    data = "prompt_type;note_text;annotation\ntype1;some note;some annotation\n"
    df = _parse_csv_flexible(data, FEWSHOT_COLS)
    assert list(df.columns) == FEWSHOT_COLS
    assert len(df) == 1


def test_actual_sample_file():
    """Integration test with the real sample file on disk."""
    import os
    sample_path = os.path.join(
        os.path.dirname(__file__), '..', 'small_testing_data', 'small_patients_notes_examples.csv'
    )
    if not os.path.exists(sample_path):
        pytest.skip("Sample file not found")
    with open(sample_path, 'r', encoding='utf-8') as f:
        contents = f.read()
    df = _parse_csv_flexible(contents, REQUIRED_COLS)
    assert 'text' in df.columns
    assert 'date' in df.columns
    assert len(df) > 0
    # Verify no stray quotes in column values
    for col in REQUIRED_COLS:
        for val in df[col]:
            assert not val.startswith('"'), f"Stray quote in {col}: {val[:50]}"


def test_text_with_semicolons_reconstructed():
    """Text field containing ; is fully preserved (not truncated)."""
    data = (
        '"text;""date"";""p_id"";""note_id"";""report_type"""\n'
        '"""""""First part; second part; third part"""""";""2024-01-01"";""1"";""100"";""CCE"""\n'
    )
    df = _parse_csv_flexible(data, REQUIRED_COLS)
    assert len(df) == 1
    text_val = df.iloc[0]['text']
    assert 'second part' in text_val
    assert 'third part' in text_val


def test_text_with_semicolons_and_annotations():
    """Both text and annotations columns present, text contains ;, all fields correct."""
    data = (
        '"text;""date"";""p_id"";""note_id"";""report_type"";""annotations"""\n'
        '"""""""Part A; Part B"""""";""2024-01-01"";""42"";""200"";""CCE"";""some annotation"""\n'
    )
    required = REQUIRED_COLS + ['annotations']
    df = _parse_csv_flexible(data, required)
    assert len(df) == 1
    assert 'Part A' in df.iloc[0]['text']
    assert 'Part B' in df.iloc[0]['text']
    assert df.iloc[0]['p_id'] == '42'
    assert 'annotation' in df.iloc[0]['annotations']


def test_actual_sample_file_text_not_truncated():
    """Integration test: text fields in real sample CSV are not truncated."""
    import os
    sample_path = os.path.join(
        os.path.dirname(__file__), '..', 'small_testing_data', 'small_patients_notes_examples.csv'
    )
    if not os.path.exists(sample_path):
        pytest.skip("Sample file not found")
    with open(sample_path, 'r', encoding='utf-8') as f:
        contents = f.read()
    df = _parse_csv_flexible(contents, REQUIRED_COLS)
    assert len(df) == 4

    # Row 0: text contains "ETICHETTA" after the first ;
    assert 'ETICHETTA' in df.iloc[0]['text']
    assert df.iloc[0]['date'] == '2019-10-11'
    assert df.iloc[0]['p_id'] == '999012'
    assert df.iloc[0]['report_type'] == 'CCE'

    # Row 1: text also contains ETICHETTA
    assert 'ETICHETTA' in df.iloc[1]['text']

    # Row 3 (Pathology row): text mentions DIAGNOSI
    assert 'DIAGNOSI' in df.iloc[3]['text']
    assert df.iloc[3]['report_type'] == 'Pathology'

    # Annotations should be present and non-empty
    if 'annotations' in df.columns:
        for i in range(len(df)):
            ann = df.iloc[i]['annotations']
            assert ann and len(ann.strip()) > 0, f"Row {i} annotations empty"


def test_simple_csv_still_works():
    """Regression: standard CSV without "" wrapping still parses correctly."""
    data = "text;date;p_id;note_id;report_type\nSimple text;2024-01-01;1;100;CCE\nAnother note;2024-02-01;2;101;Pathology\n"
    df = _parse_csv_flexible(data, REQUIRED_COLS)
    assert len(df) == 2
    assert df.iloc[0]['text'] == 'Simple text'
    assert df.iloc[1]['report_type'] == 'Pathology'


def test_reconstruction_with_no_extra_semicolons():
    """Reconstruction path works when text has no internal ;."""
    data = (
        '"text;""date"";""p_id"";""note_id"";""report_type"""\n'
        '"""""""No semicolons here"""""";""2024-01-01"";""5"";""300"";""CCE"""\n'
    )
    df = _parse_csv_with_reconstruction(data, REQUIRED_COLS)
    assert df is not None
    assert len(df) == 1
    assert 'No semicolons here' in df.iloc[0]['text']
    assert df.iloc[0]['p_id'] == '5'


# ---------------------------------------------------------------------------
# BOM / encoding regression tests — hardening against Excel-produced files
# ---------------------------------------------------------------------------

def test_fewshot_csv_with_utf8_bom():
    """Excel on Windows saves UTF-8 files with a BOM (\ufeff) — first column
    name ends up as '\ufeffprompt_type' and the parser must tolerate it."""
    data = "\ufeffprompt_type,note_text,annotation\ntype1,some note,some ann\n"
    df = _parse_csv_flexible(data, FEWSHOT_COLS)
    assert list(df.columns) == FEWSHOT_COLS
    assert df.iloc[0]['prompt_type'] == 'type1'


def test_patients_csv_with_utf8_bom_semicolon():
    """Patient-notes CSV with UTF-8 BOM and semicolon delimiter."""
    data = "\ufefftext;date;p_id;note_id;report_type\nhello;2024-01-01;1;100;CCE\n"
    df = _parse_csv_flexible(data, REQUIRED_COLS)
    assert 'text' in df.columns
    assert df.iloc[0]['text'] == 'hello'


def test_bom_in_reconstruction_path():
    """BOM survives when the reconstruction path handles the broken-quoting format."""
    data = (
        '\ufeff"text;""date"";""p_id"";""note_id"";""report_type"""\n'
        '"some text;""2024-01-01"";""1"";""100"";""CCE"""\n'
    )
    df = _parse_csv_flexible(data, REQUIRED_COLS)
    assert 'text' in df.columns
    assert df.iloc[0]['p_id'] == '1'


def test_decode_strips_utf8_bom():
    """_decode_csv_bytes transparently handles UTF-8 with BOM."""
    raw = ("prompt_type,note_text,annotation\ntype1,a,b\n").encode("utf-8-sig")
    text = _decode_csv_bytes(raw)
    assert not text.startswith("\ufeff")
    assert text.startswith("prompt_type")


def test_decode_handles_utf16():
    """_decode_csv_bytes falls back to UTF-16 when UTF-8 decoding fails."""
    raw = "prompt_type,note_text,annotation\ntype1,a,b\n".encode("utf-16")
    text = _decode_csv_bytes(raw)
    assert "prompt_type" in text


def test_decode_handles_latin1_fallback():
    """_decode_csv_bytes falls back to latin-1 for non-UTF bytes (e.g. legacy Excel)."""
    # 0xE9 is 'é' in latin-1 but invalid in utf-8
    raw = b"prompt_type,note_text,annotation\ntype1,caf\xe9,ann\n"
    text = _decode_csv_bytes(raw)
    assert "prompt_type" in text
    assert "caf" in text


def test_headerless_fewshot_csv_is_accepted():
    """Real user-provided CSV: no header row at all, just data. Regression for
    the few_shot_trg1.csv sample. The parser injects the required column
    names when the row width matches AND a field is long enough to clearly
    be note text rather than a column name."""
    long_note = 'NOTATKA LEKARSKA TELERADIOTERAPII - PRZYJECIE Data 2023-06-27 Pacjent przyjety celem rozpoczecia radioterapii'
    data = (
        f'radiotherapy_start, "{long_note}" ,'
        '"pre-operative radiotherapy started on 2023-06-27."\n'
        f'radiotherapy_start, "{long_note}",'
        '"pre-operative radiotherapy started 2023-06-21."\n'
    )
    df = _parse_csv_flexible(data, FEWSHOT_COLS)
    assert list(df.columns) == FEWSHOT_COLS
    assert len(df) == 2
    assert df.iloc[0]['prompt_type'] == 'radiotherapy_start'
    assert 'NOTATKA' in df.iloc[0]['note_text']
    assert 'pre-operative' in df.iloc[0]['annotation']


def test_headerless_with_trailing_blank_line():
    """Trailing blank line (like the user's file) must not break headerless mode."""
    long_note = 'Some clinical note long enough to clearly be data rather than a column header'
    data = (
        f'radiotherapy_start,"{long_note}","some annotation"\n'
        '\n'
    )
    df = _parse_csv_flexible(data, FEWSHOT_COLS)
    assert list(df.columns) == FEWSHOT_COLS
    assert len(df) == 1


def test_wrong_named_header_still_fails_clearly():
    """A file with a real (short) header whose names don't match the required
    ones must NOT be silently treated as headerless — we'd load garbage.
    The error should instead surface the column names found."""
    data = "type;text;label\ntype1;some note;some ann\n"
    with pytest.raises(HTTPException) as exc_info:
        _parse_csv_flexible(data, FEWSHOT_COLS)
    detail = exc_info.value.detail
    assert "type" in detail and "text" in detail and "label" in detail


def test_headerless_fallback_rejects_wrong_column_count():
    """Files with the wrong number of columns (no header AND width mismatch)
    should still fail loudly — we don't silently accept malformed files."""
    data = 'only_two,columns\nhere,too\n'
    with pytest.raises(HTTPException) as exc_info:
        _parse_csv_flexible(data, FEWSHOT_COLS)
    assert exc_info.value.status_code == 400


def test_actual_user_sample_few_shot_trg1():
    """Integration test with the real file the user reported as failing."""
    import os
    sample_path = os.path.join(
        os.path.dirname(__file__), '..', 'few_shot_trg1.csv'
    )
    if not os.path.exists(sample_path):
        pytest.skip("Sample file not found")
    with open(sample_path, 'rb') as f:
        raw = f.read()
    from routes.upload import _decode_csv_bytes as _decode
    df = _parse_csv_flexible(_decode(raw), FEWSHOT_COLS)
    assert list(df.columns) == FEWSHOT_COLS
    assert len(df) >= 3
    # Every row must have the Polish note text and a sensible annotation
    for i in range(len(df)):
        assert df.iloc[i]['prompt_type'] == 'radiotherapy_start'
        assert 'NOTATKA' in df.iloc[i]['note_text']
        assert 'radiotherapy' in df.iloc[i]['annotation']


def test_error_message_includes_found_columns():
    """When parsing fails, the error lists the columns that were actually found
    so the user can see what went wrong at a glance."""
    data = "type;text;label\ntype1;some note;some ann\n"
    with pytest.raises(HTTPException) as exc_info:
        _parse_csv_flexible(data, FEWSHOT_COLS)
    detail = exc_info.value.detail
    assert "prompt_type" in detail  # required columns listed
    # Found columns should be surfaced so the user can spot the naming mismatch
    assert "type" in detail and "text" in detail and "label" in detail
