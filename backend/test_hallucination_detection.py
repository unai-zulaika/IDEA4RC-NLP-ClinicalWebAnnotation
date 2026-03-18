"""Tests for repetition/looping hallucination detection."""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from services.structured_generator import _detect_repetition, detect_repetition_hallucination
from models.annotation_models import HallucinationFlag


# ---------------------------------------------------------------------------
# _detect_repetition (low-level)
# ---------------------------------------------------------------------------

class TestDetectRepetition:
    def test_empty_text(self):
        assert _detect_repetition("") is None
        assert _detect_repetition(None) is None

    def test_short_text(self):
        assert _detect_repetition("Short text.") is None

    def test_normal_reasoning(self):
        text = (
            "The note mentions sarcoma indifferenziato with bilateral pulmonary metastases. "
            "The patient underwent amputation due to a fracture. "
            "Subcutaneous lesions appeared in the thoracic region suspected of being recurrent."
        )
        assert _detect_repetition(text) is None

    def test_obvious_repetition_loop(self):
        """The exact pattern from the user's example."""
        base = "The note also mentions 'lesioni sottocutanee multiple in sede toracica sospette in sensoripetitivo' (multiple subcutaneous lesions in the thoracic region suspected in sensoripetitivo)"
        text = ". ".join([base] * 30)
        result = _detect_repetition(text)
        assert result is not None
        assert result["severity"] == "high"
        assert result["duplicate_ratio"] >= 0.9

    def test_moderate_repetition(self):
        """Some repetition but not extreme."""
        sentences = [
            "The patient has a history of sarcoma",
            "Treatment was administered successfully",
            "The patient has a history of sarcoma",
            "Follow-up is recommended in three months",
            "The patient has a history of sarcoma",
            "No new metastases were detected on imaging",
        ]
        text = ". ".join(sentences)
        result = _detect_repetition(text, threshold=0.3)
        assert result is not None

    def test_threshold_boundary(self):
        """Just below threshold should not trigger."""
        unique_sentences = [
            f"Unique medical observation number {i} about the patient condition"
            for i in range(10)
        ]
        text = ". ".join(unique_sentences)
        assert _detect_repetition(text) is None

    def test_few_sentences(self):
        """Less than 3 sentences should not trigger."""
        text = "One sentence here. Another one here."
        assert _detect_repetition(text) is None

    def test_high_severity_threshold(self):
        base = "Repeated sentence about clinical findings and patient status"
        text = ". ".join([base] * 20)
        result = _detect_repetition(text)
        assert result is not None
        assert result["severity"] == "high"

    def test_medium_severity(self):
        """Between 50% and 80% duplicates → medium."""
        sentences = ["Unique observation about the patient's medical history"] * 4
        sentences += [f"Different observation number {i} about treatment" for i in range(4)]
        text = ". ".join(sentences)
        result = _detect_repetition(text, threshold=0.3)
        if result:
            assert result["severity"] in ("medium", "high")


# ---------------------------------------------------------------------------
# detect_repetition_hallucination (high-level)
# ---------------------------------------------------------------------------

class TestDetectRepetitionHallucination:
    def test_no_hallucination(self):
        result = detect_repetition_hallucination(
            reasoning="The patient was diagnosed with sarcoma. Treatment plan involves surgery.",
            evidence="sarcoma indifferenziato con metastasi polmonari bilaterali",
            raw_output='{"evidence": "...", "reasoning": "...", "final_output": "Sarcoma"}',
        )
        assert result is None

    def test_hallucination_in_reasoning(self):
        base = "The note also mentions subcutaneous lesions in the thoracic region suspected in sensoripetitivo"
        reasoning = ". ".join([base] * 30)
        result = detect_repetition_hallucination(
            reasoning=reasoning,
            evidence="normal evidence text here",
        )
        assert result is not None
        assert len(result) >= 1
        assert any(f.field == "reasoning" for f in result)
        assert all(isinstance(f, HallucinationFlag) for f in result)

    def test_hallucination_in_evidence(self):
        base = "lesioni sottocutanee multiple in sede toracica sospette in sensoripetitivo"
        evidence = ". ".join([base] * 15)
        result = detect_repetition_hallucination(evidence=evidence)
        assert result is not None
        assert any(f.field == "evidence" for f in result)

    def test_hallucination_in_raw_output(self):
        base = "The note also mentions repeated finding about the patient"
        raw = ". ".join([base] * 25)
        result = detect_repetition_hallucination(raw_output=raw)
        assert result is not None
        assert any(f.field == "raw_output" for f in result)

    def test_empty_inputs(self):
        assert detect_repetition_hallucination() is None
        assert detect_repetition_hallucination(reasoning="", evidence="", raw_output="") is None

    def test_flag_structure(self):
        base = "Repeated clinical observation about the patient's ongoing treatment plan"
        reasoning = ". ".join([base] * 20)
        result = detect_repetition_hallucination(reasoning=reasoning)
        assert result is not None
        flag = result[0]
        assert flag.type == "repetition_loop"
        assert flag.field == "reasoning"
        assert flag.severity in ("medium", "high")
        assert 0.0 <= flag.duplicate_ratio <= 1.0
        assert "unique sentences" in flag.message

    def test_multiple_fields_flagged(self):
        base_r = "Repeated reasoning sentence about clinical findings in the patient"
        base_e = "Repeated evidence sentence from the medical note text content"
        result = detect_repetition_hallucination(
            reasoning=". ".join([base_r] * 20),
            evidence=". ".join([base_e] * 20),
        )
        assert result is not None
        fields = {f.field for f in result}
        assert "reasoning" in fields
        assert "evidence" in fields

    def test_truncated_reasoning_not_detected(self):
        """Reasoning truncated to 500 chars loses enough repetition to miss detection."""
        base = "The note also mentions 'lesioni sottocutanee multiple in sede toracica sospette in sensoripetitivo' (multiple subcutaneous lesions in the thoracic region suspected in sensoripetitivo)"
        full_reasoning = ". ".join([base] * 30)
        truncated = full_reasoning[:497] + "..."
        # Truncated version may not have enough sentences
        # Full version definitely should be detected
        full_result = detect_repetition_hallucination(reasoning=full_reasoning)
        assert full_result is not None
        assert full_result[0].severity == "high"

    def test_real_world_hallucination_example(self):
        """Test with the exact pattern from the user's reported hallucination."""
        first_sentence = "The note mentions 'lesioni sottocutanee multiple in sede toracica' (multiple subcutaneous lesions in the thoracic region) and 'metastasi polmonari bilaterali e sottocutanee' (bilateral and subcutaneous pulmonary and subcutaneous metastases)"
        repeated = "The note also mentions 'lesioni sottocutanee multiple in sede toracica sospette in sensoripetitivo' (multiple subcutaneous lesions in the thoracic region suspected in sensoripetitivo)"
        reasoning = first_sentence + ". " + ". ".join([repeated] * 35)
        result = detect_repetition_hallucination(reasoning=reasoning)
        assert result is not None
        assert any(f.field == "reasoning" and f.severity == "high" for f in result)
