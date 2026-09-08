"""
Regression tests for the audit findings fixed on this branch.

Each test pins behaviour that broke silently once already, so the failure mode
is caught by the suite rather than by a downstream data problem.
"""
import ast
import inspect
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent))


# ---------------------------------------------------------------------------
# CAW-01: the chunk loop body must actually be inside the loop
# ---------------------------------------------------------------------------

class TestChunkLoopStructure:
    """A bad merge once de-indented the whole loop body out of the `for`.

    The behavioural test (test_note_chunker.py::test_long_note_chunked_early_stop)
    covers the symptom; this pins the structure directly, because the symptom
    took six months to be noticed.
    """

    @staticmethod
    def _chunk_loop():
        source = (Path(__file__).parent / "routes" / "annotate.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
                names = [getattr(e, "id", "") for e in node.target.elts]
                if "_chunk_text" in names:
                    return node
        pytest.fail("chunk loop not found in routes/annotate.py")

    def test_loop_body_contains_the_work(self):
        loop = self._chunk_loop()
        # Prompt building alone is 1 statement; the real body is inference,
        # post-processing, extraction, evaluation and the early-stop branches.
        assert len(loop.body) > 10, (
            f"chunk loop body has only {len(loop.body)} statement(s) — the body "
            "has been de-indented out of the loop again"
        )

    def test_inference_and_post_processing_are_siblings(self):
        """post_processing must not be nested inside the vllm_inference timer.

        Nesting them makes the vllm_inference timing include all downstream work,
        which silently corrupts the performance breakdown.
        """
        loop = self._chunk_loop()
        labels = []
        for stmt in loop.body:
            if isinstance(stmt, ast.With):
                try:
                    labels.append(stmt.items[0].context_expr.args[0].value)
                except (AttributeError, IndexError):
                    pass
        assert "vllm_inference" in labels
        assert "post_processing" in labels, (
            "post_processing is not a direct child of the chunk loop — it has "
            "been nested inside the vllm_inference timer"
        )

    def test_every_chunk_is_generated_for(self):
        """The loop must build a prompt from `_chunk_text`, not a fixed note."""
        loop = self._chunk_loop()
        body_src = ast.dump(ast.Module(body=loop.body, type_ignores=[]))
        assert "_chunk_text" in body_src


# ---------------------------------------------------------------------------
# CAW-06: chunk budget must reserve the tokens generation actually requests
# ---------------------------------------------------------------------------

def test_chunk_budget_matches_generation_budget():
    from routes.annotate import _process_single_prompt

    src = inspect.getsource(_process_single_prompt)
    assert "calculate_available_tokens(_probe_prompt, max_new_tokens)" in src, (
        "the chunk budget no longer reserves the same token count that "
        "generation requests"
    )
    # Only one definition of the budget, so the two cannot drift apart again.
    assert src.count("max_new_tokens = (") == 1
    assert "fast_max_tokens" not in src


# ---------------------------------------------------------------------------
# CAW-02: identifiers must not escape their storage directory
# ---------------------------------------------------------------------------

class TestPathTraversal:
    TRAVERSALS = [
        "../config/vllm_config",
        "../../frontend/package",
        "..",
        "a/../../b",
        "....//config/vllm_config",
        "/etc/passwd",
        "",
        ".hidden",
    ]

    @pytest.mark.parametrize("bad_id", TRAVERSALS)
    def test_load_session_rejects(self, bad_id):
        from routes.sessions import _load_session
        with pytest.raises(HTTPException) as exc:
            _load_session(bad_id)
        assert exc.value.status_code == 400

    @pytest.mark.parametrize("bad_id", TRAVERSALS)
    def test_load_preset_rejects(self, bad_id):
        from routes.presets import _load_preset
        with pytest.raises(HTTPException) as exc:
            _load_preset(bad_id)
        assert exc.value.status_code == 400

    def test_valid_uuid_is_accepted(self):
        """A well-formed id must pass the validator and reach the file lookup.

        FileNotFoundError (not HTTPException 400) is the proof it got through.
        """
        from routes.sessions import _load_session
        with pytest.raises(FileNotFoundError):
            _load_session("00000000-0000-4000-8000-000000000000")

    def test_center_name_rejects_traversal(self):
        from lib.safe_paths import validate_center
        for bad in ["../evil", "a/b", "..", ""]:
            with pytest.raises(HTTPException):
                validate_center(bad)
        assert validate_center("INT-SARC") == "INT-SARC"


# ---------------------------------------------------------------------------
# CAW-05: a fuzzy site match must not masquerade as a determination
# ---------------------------------------------------------------------------

class TestTopographyMatchConfidence:
    def test_substring_of_a_word_is_not_a_match(self):
        """"test" used to resolve to C62.0 because it is a substring of "testis"."""
        from lib.topography_resolver import get_topography_resolver
        assert get_topography_resolver().resolve_text("test") is None

    def test_real_sites_still_resolve_exactly(self):
        from lib.topography_resolver import get_topography_resolver
        resolver = get_topography_resolver()
        entry = resolver.resolve_text("Testis")
        assert entry is not None
        assert entry["code"] == "C62.0"
        assert entry["match_type"] == "exact"
        assert entry["match_score"] == 1.0

    def test_absence_tokens_do_not_resolve(self):
        from lib.topography_resolver import get_topography_resolver
        resolver = get_topography_resolver()
        for token in ["unknown", "n/a", "not applicable", "none", "asdfqwer"]:
            assert resolver.resolve_text(token) is None, token

    def test_low_confidence_match_is_rejected_as_a_code(self):
        from services.diagnosis_resolver import _is_confident_match
        assert _is_confident_match({"match_type": "exact", "match_score": 1.0})
        assert _is_confident_match({"match_type": "fuzzy", "match_score": 0.9})
        assert not _is_confident_match({"match_type": "fuzzy", "match_score": 0.6})
        assert not _is_confident_match({})


def test_unknown_code_label_is_empty_not_a_combination_name():
    """CAW-07: an unknown code must not borrow the annotation's description.

    Descriptions are frequently combination names (morphology + topography),
    which mislabel a single code.
    """
    from services.diagnosis_resolver import _enrich_code_label
    assert _enrich_code_label("9999/9", "Some combination name", "histology") == ""
    assert _enrich_code_label("C99.9", "Another combination", "topography") == ""


# ---------------------------------------------------------------------------
# CAW-14: normalized-match evidence offsets must be exact
# ---------------------------------------------------------------------------

class TestEvidenceOffsets:
    def test_offset_normalizer_agrees_with_normalizer(self):
        from routes.annotate import _normalize_text, _normalize_with_offsets
        samples = [
            "Il  paziente\tha  lesioni   sottocutanee.",
            "  Tumore   dell'arto  inferiore sinistro  ",
            "Patiënt met écht ongewone naïeve café-symptomen",
            "Grading: G2\n\nProfondità: profondo",
            "", "   ", "a", "ä" * 5,
        ]
        for text in samples:
            norm, offsets = _normalize_with_offsets(text)
            assert norm == _normalize_text(text), repr(text)
            assert len(norm) == len(offsets), repr(text)

    @pytest.mark.parametrize("note,evidence", [
        ("Il paziente   ha   lesioni sottocutanee multiple in sede toracica.",
         "lesioni sottocutanee"),
        ("Profondità:   il  tumore è profondo rispetto alla fascia.",
         "il tumore e profondo"),
        ("Tumör i   nedre  extremitet, vänster lår.", "nedre extremitet"),
    ])
    def test_span_points_at_the_matching_text(self, note, evidence):
        """The returned span must slice out text equivalent to the evidence.

        Offsets used to drift by one per whitespace run before the match.
        """
        from routes.annotate import _find_evidence_in_text, _normalize_text
        span = _find_evidence_in_text(note, evidence)
        assert span is not None
        start, end = span
        assert _normalize_text(note[start:end]) == _normalize_text(evidence)


# ---------------------------------------------------------------------------
# CAW-15: few-shot annotations must be JSON-escaped in the prompt
# ---------------------------------------------------------------------------

def test_fewshot_annotation_with_quotes_stays_valid_json():
    import json
    import re
    from routes.annotate import _get_prompt, _ensure_prompts_loaded, _PROMPTS

    _ensure_prompts_loaded()
    if not _PROMPTS:
        pytest.skip("No prompts loaded")
    prompt_type = next(iter(_PROMPTS))

    tricky = 'Histological type: "spindle cell" sarcoma \\ NOS.'
    prompt = _get_prompt(
        task_key=prompt_type,
        fewshots=[("Some note text.", tricky)],
        note_text="A note.",
    )
    match = re.search(r'- Response: (\{"final_output".*?\})\n', prompt + "\n")
    assert match, "few-shot example block not found in prompt"
    assert json.loads(match.group(1))["final_output"] == tricky


# ---------------------------------------------------------------------------
# CAW-03: few-shot retrieval mode must be reported, not silently degraded
# ---------------------------------------------------------------------------

class TestFewshotSourceReporting:
    def test_retrieval_status_reports_a_known_mode(self):
        from routes.annotate import get_fewshot_retrieval_status
        status = get_fewshot_retrieval_status()
        assert status["mode"] in {"faiss", "static", "none"}
        # A degraded mode must always carry a reason an operator can act on.
        if status["mode"] != "faiss":
            assert status["error"], "degraded retrieval must explain why"

    def test_examples_come_back_with_their_source(self):
        from routes.annotate import _get_fewshot_examples
        examples, source = _get_fewshot_examples("gender-int-sarc", "some note", k=2)
        assert source in {"faiss", "static", "none"}
        if examples:
            assert source in {"faiss", "static"}

    def test_status_probes_retrieval_rather_than_counting_indexes(self, monkeypatch):
        """Loaded indexes are not proof retrieval works.

        The .index files load while their .parquet sidecars (holding the example
        text) can be unreadable — a missing pyarrow does exactly this — and
        retrieval then silently falls back to first-k. Counting indexes reported
        a false green; the status must reflect what a real probe returns.
        """
        import routes.annotate as ra

        class FakeBuilder:
            indexes = {"biopsygrading-int-sarc": object()}

        monkeypatch.setattr(ra, "_get_fewshot_builder", lambda: FakeBuilder())
        monkeypatch.setattr(ra, "_simple_fewshots", {"biopsygrading-int-sarc": [("n", "a")]})

        monkeypatch.setattr(ra, "_get_fewshot_examples", lambda *a, **k: ([("n", "a")], "static"))
        degraded = ra.get_fewshot_retrieval_status()
        assert degraded["mode"] == "static", "index count masked a degraded retrieval"
        assert degraded["indexes"] == 1
        assert "pyarrow" in degraded["error"]

        monkeypatch.setattr(ra, "_get_fewshot_examples", lambda *a, **k: ([("n", "a")], "faiss"))
        healthy = ra.get_fewshot_retrieval_status()
        assert healthy["mode"] == "faiss"
        assert healthy["error"] is None

    def test_annotation_result_carries_the_source_field(self):
        from models.schemas import AnnotationResult
        result = AnnotationResult(prompt_type="x", annotation_text="y")
        assert hasattr(result, "fewshot_source")
        assert hasattr(result, "fewshot_count")


# ---------------------------------------------------------------------------
# CAW-09: a prompt present in only one store must still resolve
# ---------------------------------------------------------------------------

def test_mode_only_prompt_resolves_instead_of_raising():
    from routes.annotate import (
        _get_prompt_template, _ensure_prompts_loaded, _ensure_fast_prompts_loaded,
        _PROMPTS, _FAST_PROMPTS,
    )
    _ensure_prompts_loaded()
    _ensure_fast_prompts_loaded()

    fast_only = [k for k in _FAST_PROMPTS if k not in _PROMPTS]
    std_only = [k for k in _PROMPTS if k not in _FAST_PROMPTS]

    for key in fast_only[:3]:
        assert _get_prompt_template(key, fast_mode=True)
        assert _get_prompt_template(key, fast_mode=False)
    for key in std_only[:3]:
        assert _get_prompt_template(key, fast_mode=True)
        assert _get_prompt_template(key, fast_mode=False)

    with pytest.raises(KeyError):
        _get_prompt_template("no-such-prompt-anywhere", fast_mode=False)


# ---------------------------------------------------------------------------
# CAW-04: session writes must be atomic and lockable
# ---------------------------------------------------------------------------

class TestSessionWriteSafety:
    def test_save_is_atomic_and_leaves_no_temp_files(self, tmp_path, monkeypatch):
        from routes import sessions as s
        monkeypatch.setattr(s, "_get_sessions_dir", lambda: tmp_path)
        s._save_session("atomic-test", {"notes": [], "annotations": {}})
        assert (tmp_path / "atomic-test.json").exists()
        assert not list(tmp_path.glob("*.tmp"))

    def test_merge_does_not_clobber_concurrent_edits(self, tmp_path, monkeypatch):
        """A stale in-memory copy must not overwrite an edit made meanwhile."""
        from routes import sessions as s
        monkeypatch.setattr(s, "_get_sessions_dir", lambda: tmp_path)

        s._save_session("merge-test", {"notes": [], "annotations": {}})
        stale = s._load_session("merge-test")          # long-running run reads this

        # Someone edits a different note while that run is in flight.
        with s.mutate_session("merge-test") as live:
            live["annotations"]["note-b"] = {"human": "edited"}

        # The run writes its own note back via the merge path.
        s.merge_note_annotations("merge-test", "note-a", {"gender": {"v": 1}})

        final = s._load_session("merge-test")
        assert final["annotations"]["note-a"] == {"gender": {"v": 1}}
        assert final["annotations"]["note-b"] == {"human": "edited"}, (
            "the concurrent human edit was lost"
        )
        assert "note-b" not in stale.get("annotations", {})
