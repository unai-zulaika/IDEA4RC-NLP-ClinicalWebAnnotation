"""Tests for flexible CSV parsing in upload route."""

import pytest
from fastapi import HTTPException
from routes.upload import _parse_csv_flexible, _parse_csv_with_reconstruction


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
