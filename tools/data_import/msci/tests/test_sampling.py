"""Spec section: 3_split_csvs.py sampling and selection rules."""
import csv
import importlib.util
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("split_csvs", _HERE / "3_split_csvs.py")
split_csvs = importlib.util.module_from_spec(_spec)
sys.modules["split_csvs"] = split_csvs
_spec.loader.exec_module(split_csvs)


def _write_enriched(tmp_path: Path, notes: list[dict]) -> Path:
    p = tmp_path / "enriched.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for n in notes:
            f.write(json.dumps(n) + "\n")
    return p


def _write_mapping(tmp_path: Path, mapping: dict[int, str]) -> Path:
    p = tmp_path / "mapping.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["node_id", "node_sentence", "suggested_prompt_type", "confidence", "notes"])
        for node_id, prompt in mapping.items():
            w.writerow([node_id, f"sentence-{node_id}", prompt, "high", ""])
    return p


def _read_csv(path: Path, delim: str = ";") -> list[dict]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=delim))


def _make_note(note_id: str, items: list[dict]) -> dict:
    return {
        "internal_note_id": note_id,
        "pid": f"P{note_id}",
        "note_original_text": f"text for note {note_id}",
        "note_name": "Visit note",
        "note_date": "2024-01-01T00:00:00.000Z",
        "data_items": items,
    }


def _make_item(node_id: int, text_content: str, is_complete: bool = True) -> dict:
    return {
        "internal_note_id": "ignored",
        "sentence_id": 1,
        "dict_id": 199,
        "node_id": node_id,
        "text_content": text_content,
        "params": "x",
        "node_sentence": f"template {node_id}",
        "is_complete": is_complete,
        "incomplete_reason": None if is_complete else "unfilled_placeholder",
    }


def test_split_by_usability(tmp_path):
    """Notes with usable items → fewshots; notes without → upload."""
    notes = [
        _make_note("N1", [_make_item(56, "Patient's gender female.")]),  # usable
        _make_note("N2", []),  # no items → upload
        _make_note("N3", [_make_item(999, "Mapped to nothing")]),  # not in mapping → upload
    ]
    enriched = _write_enriched(tmp_path, notes)
    mapping = _write_mapping(tmp_path, {56: "gender"})
    out = tmp_path / "out"

    rc = split_csvs.main([
        "--enriched", str(enriched),
        "--mapping", str(mapping),
        "--center", "MSCI",
        "--out-dir", str(out),
        "--min-per-prompt", "1",
        "--max-per-prompt", "10",
    ])
    assert rc == 0

    fewshots = _read_csv(out / "fewshots_msci.csv")
    upload = _read_csv(out / "upload_msci.csv")
    faiss = _read_csv(out / "fewshots_msci_faiss.csv", delim=",")

    fewshot_ids = {r["note_id"] for r in fewshots}
    upload_ids = {r["note_id"] for r in upload}
    assert fewshot_ids == {"N1"}
    assert upload_ids == {"N2", "N3"}
    # Mutual exclusion
    assert fewshot_ids & upload_ids == set()
    # FAISS picks up the single complete usable item
    assert len(faiss) == 1
    assert faiss[0]["prompt_type"] == "gender"


def _setup_completeness_fixture(tmp_path):
    """Helper: one note with one complete + one incomplete data_item."""
    notes = [
        _make_note("N1", [
            _make_item(56, "Patient's gender male.", is_complete=True),
            _make_item(89, "Tumor diameter: [put value]mm", is_complete=False),
        ]),
    ]
    enriched = _write_enriched(tmp_path, notes)
    mapping = _write_mapping(tmp_path, {56: "gender", 89: "tumordiameter"})
    return enriched, mapping


def test_incomplete_items_excluded_from_faiss_in_strict_mode(tmp_path):
    """With --faiss-strict, incomplete data_items are filtered from FAISS but
    still render in fewshots_msci.csv with their [...] left intact.
    """
    enriched, mapping = _setup_completeness_fixture(tmp_path)
    out = tmp_path / "out"
    rc = split_csvs.main([
        "--enriched", str(enriched), "--mapping", str(mapping),
        "--center", "MSCI", "--out-dir", str(out),
        "--min-per-prompt", "1", "--max-per-prompt", "10",
        "--faiss-strict",
    ])
    assert rc == 0

    fewshots = _read_csv(out / "fewshots_msci.csv")
    faiss = _read_csv(out / "fewshots_msci_faiss.csv", delim=",")
    assert len(fewshots) == 1
    annotations = fewshots[0]["annotations"]
    assert "gender-msci: Patient's gender male." in annotations
    assert "tumordiameter-msci: Tumor diameter: [put value]mm" in annotations
    # Strict mode: only the complete one in FAISS
    assert len(faiss) == 1
    assert faiss[0]["prompt_type"] == "gender"


def test_incomplete_items_included_in_faiss_by_default(tmp_path):
    """Default mode (relaxed) lets incomplete items into the FAISS pool. This
    is the option chosen for MSCI so that the 3 prompts whose source export
    has no fully-complete data_items still get few-shot examples.
    """
    enriched, mapping = _setup_completeness_fixture(tmp_path)
    out = tmp_path / "out"
    rc = split_csvs.main([
        "--enriched", str(enriched), "--mapping", str(mapping),
        "--center", "MSCI", "--out-dir", str(out),
        "--min-per-prompt", "1", "--max-per-prompt", "10",
    ])
    assert rc == 0

    faiss = _read_csv(out / "fewshots_msci_faiss.csv", delim=",")
    prompts = {r["prompt_type"] for r in faiss}
    # Both prompts appear; the incomplete item's annotation still lands as text
    assert prompts == {"gender", "tumordiameter"}
    tumordia = [r for r in faiss if r["prompt_type"] == "tumordiameter"][0]
    assert "[put value]" in tumordia["annotation"]


def test_faiss_sampling_caps_at_max(tmp_path):
    """If qualifying count > max, exactly max are sampled."""
    notes = [
        _make_note(f"N{i}", [_make_item(56, f"Patient's gender female ({i}).", True)])
        for i in range(100)
    ]
    enriched = _write_enriched(tmp_path, notes)
    mapping = _write_mapping(tmp_path, {56: "gender"})
    out = tmp_path / "out"

    rc = split_csvs.main([
        "--enriched", str(enriched), "--mapping", str(mapping),
        "--center", "MSCI", "--out-dir", str(out),
        "--min-per-prompt", "30", "--max-per-prompt", "60", "--seed", "42",
    ])
    assert rc == 0
    faiss = _read_csv(out / "fewshots_msci_faiss.csv", delim=",")
    assert len(faiss) == 60


def test_faiss_sampling_below_max_keeps_all(tmp_path):
    """If qualifying count ≤ max, all are kept (even when < min)."""
    notes = [
        _make_note(f"N{i}", [_make_item(56, "x", True)])
        for i in range(5)
    ]
    enriched = _write_enriched(tmp_path, notes)
    mapping = _write_mapping(tmp_path, {56: "gender"})
    out = tmp_path / "out"

    rc = split_csvs.main([
        "--enriched", str(enriched), "--mapping", str(mapping),
        "--center", "MSCI", "--out-dir", str(out),
        "--min-per-prompt", "30", "--max-per-prompt", "60",
    ])
    assert rc == 0
    faiss = _read_csv(out / "fewshots_msci_faiss.csv", delim=",")
    assert len(faiss) == 5


def test_faiss_sampling_deterministic_with_seed(tmp_path):
    notes = [
        _make_note(f"N{i}", [_make_item(56, f"text {i}", True)])
        for i in range(100)
    ]
    enriched = _write_enriched(tmp_path, notes)
    mapping = _write_mapping(tmp_path, {56: "gender"})

    def _run(out_dir: Path, seed: int):
        split_csvs.main([
            "--enriched", str(enriched), "--mapping", str(mapping),
            "--center", "MSCI", "--out-dir", str(out_dir),
            "--min-per-prompt", "10", "--max-per-prompt", "20",
            "--seed", str(seed),
        ])
        return [r["annotation"] for r in _read_csv(out_dir / "fewshots_msci_faiss.csv", delim=",")]

    a = _run(tmp_path / "a", 42)
    b = _run(tmp_path / "b", 42)
    c = _run(tmp_path / "c", 99)
    assert a == b
    assert a != c


def test_note_can_appear_under_multiple_prompts(tmp_path):
    notes = [
        _make_note("N1", [
            _make_item(56, "Patient's gender female.", True),
            _make_item(89, "Tumor longest diameter: 45mm.", True),
        ]),
    ]
    enriched = _write_enriched(tmp_path, notes)
    mapping = _write_mapping(tmp_path, {56: "gender", 89: "tumordiameter"})
    out = tmp_path / "out"

    split_csvs.main([
        "--enriched", str(enriched), "--mapping", str(mapping),
        "--center", "MSCI", "--out-dir", str(out),
        "--min-per-prompt", "1", "--max-per-prompt", "10",
    ])
    faiss = _read_csv(out / "fewshots_msci_faiss.csv", delim=",")
    prompts_for_n1 = [r["prompt_type"] for r in faiss]
    assert sorted(prompts_for_n1) == ["gender", "tumordiameter"]


def test_missing_mapping_file_is_fatal(tmp_path):
    notes = [_make_note("N1", [])]
    enriched = _write_enriched(tmp_path, notes)
    out = tmp_path / "out"

    rc = split_csvs.main([
        "--enriched", str(enriched),
        "--mapping", str(tmp_path / "does_not_exist.csv"),
        "--center", "MSCI", "--out-dir", str(out),
    ])
    assert rc == 1
