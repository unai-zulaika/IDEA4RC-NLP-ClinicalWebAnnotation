"""Completeness rule from the spec, exhaustive matrix."""
from pathlib import Path

from common import (
    CodebookEntry,
    DataItem,
    check_completeness,
    load_codebook,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _cb(param_count: int, dict_id: int = 199, node_id: int = 56) -> dict:
    """Build an in-memory codebook with a single entry."""
    return {
        (dict_id, node_id): CodebookEntry(
            dict_id=dict_id,
            node_id=node_id,
            node_sentence="dummy",
            param_count=param_count,
        )
    }


def _item(**kw) -> DataItem:
    defaults = dict(
        internal_note_id="N",
        sentence_id=1,
        dict_id=199,
        node_id=56,
        text_content="Patient's gender female.",
        params="female",
    )
    defaults.update(kw)
    return DataItem(**defaults)


def test_filled_params_is_complete():
    ok, reason = check_completeness(_item(), _cb(1))
    assert ok and reason is None


def test_no_placeholder_entry_with_empty_params_is_complete():
    """Codebook entries with parameters=[] (assertions like 'No previous cancer
    treatments') don't need params filled."""
    item = _item(
        node_id=70,
        text_content="No previous cancer treatments",
        params="",
    )
    ok, reason = check_completeness(item, _cb(0, node_id=70))
    assert ok and reason is None


def test_unfilled_placeholder_in_text_is_incomplete():
    item = _item(text_content="Tumor diameter: [put value]mm", params="some")
    ok, reason = check_completeness(item, _cb(1))
    assert not ok and reason == "unfilled_placeholder"


def test_empty_params_when_placeholders_expected_is_incomplete():
    item = _item(text_content="Patient's gender done.", params="   ")
    ok, reason = check_completeness(item, _cb(1))
    assert not ok and reason == "empty_params"


def test_polish_dict_is_incomplete():
    item = _item(dict_id=110, node_id=35)
    cb = _cb(1, dict_id=110, node_id=35)
    ok, reason = check_completeness(item, cb)
    assert not ok and reason == "polish_dict"


def test_unknown_node_id_is_incomplete():
    item = _item(node_id=999)
    ok, reason = check_completeness(item, _cb(1, node_id=56))
    assert not ok and reason == "unknown_node_id"


def test_empty_text_content_is_incomplete():
    item = _item(text_content="   ")
    ok, reason = check_completeness(item, _cb(1))
    assert not ok and reason == "empty_text_content"


def test_load_codebook_fixture_counts():
    """Sanity: the test fixture parses to the expected number of entries."""
    cb = load_codebook(FIXTURES / "data_items_def.json")
    # 4 english (dict_id=199) + 1 polish (dict_id=110) = 5
    assert len(cb) == 5
    assert (199, 56) in cb
    assert cb[(199, 56)].param_count == 1
    assert cb[(199, 70)].param_count == 0  # no-placeholder assertion
    assert cb[(110, 35)].param_count == 1
