"""
Tests for the structured output parsing pipeline.

Tests parse_structured_annotation() across all layers:
- Layer 1: Direct JSON parse (guided decoding output)
- Layer 2: Thinking block handling
- Layer 3: JSON extraction from markdown/wrapper text
- Layer 4: Regex fallback
"""
import json
import pytest
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from models.annotation_models import StructuredAnnotation, FastStructuredAnnotation, AnnotationDateInfo
from services.structured_generator import (
    parse_structured_annotation,
    FAST_ANNOTATION_JSON_SCHEMA,
    generate_structured_annotation_fallback,
    ANNOTATION_JSON_SCHEMA,
    _strip_thinking_blocks,
    _extract_json_string,
    build_per_prompt_schema,
    get_prompt_schema,
)


# ---------------------------------------------------------------------------
# Test: StructuredAnnotation model validators
# ---------------------------------------------------------------------------

class TestStructuredAnnotationValidators:
    """Test Pydantic field validators on StructuredAnnotation."""

    def test_placeholder_replacement(self):
        """Placeholders like [select ...] should be replaced with 'Not applicable'."""
        ann = StructuredAnnotation(
            final_output="Treatment: [select intention]",
            evidence="some text",
        )
        assert ann.final_output == "Not applicable"

    def test_placeholder_case_insensitive(self):
        ann = StructuredAnnotation(
            final_output="Date: [Put date here]",
        )
        assert ann.final_output == "Not applicable"

    def test_normal_output_unchanged(self):
        ann = StructuredAnnotation(
            final_output="Infiltrating duct carcinoma",
        )
        assert ann.final_output == "Infiltrating duct carcinoma"

    def test_reasoning_truncation(self):
        long_reasoning = "A" * 600
        ann = StructuredAnnotation(
            final_output="test",
            reasoning=long_reasoning,
        )
        assert len(ann.reasoning) == 500
        assert ann.reasoning.endswith("...")

    def test_reasoning_short_unchanged(self):
        ann = StructuredAnnotation(
            final_output="test",
            reasoning="Short reasoning.",
        )
        assert ann.reasoning == "Short reasoning."


# ---------------------------------------------------------------------------
# Test: JSON Schema generation
# ---------------------------------------------------------------------------

class TestJSONSchemaGeneration:
    """Test that JSON schema is correctly generated for vLLM response_format."""

    def test_schema_structure(self):
        assert ANNOTATION_JSON_SCHEMA["type"] == "json_schema"
        assert "json_schema" in ANNOTATION_JSON_SCHEMA
        assert ANNOTATION_JSON_SCHEMA["json_schema"]["name"] == "structured_annotation"

    def test_schema_has_required_fields(self):
        schema = ANNOTATION_JSON_SCHEMA["json_schema"]["schema"]
        props = schema.get("properties", {})
        assert "evidence" in props
        assert "reasoning" in props
        assert "final_output" in props
        assert "is_negated" in props
        assert "date" in props

    def test_schema_descriptions_populated(self):
        schema = ANNOTATION_JSON_SCHEMA["json_schema"]["schema"]
        props = schema.get("properties", {})
        # All fields should have descriptions
        for field_name in ["evidence", "reasoning", "final_output", "is_negated", "date"]:
            assert "description" in props[field_name], f"Missing description for {field_name}"

    def test_schema_is_valid_json(self):
        """Schema should be serializable to JSON (required for API call)."""
        serialized = json.dumps(ANNOTATION_JSON_SCHEMA)
        assert len(serialized) > 0
        parsed = json.loads(serialized)
        assert parsed == ANNOTATION_JSON_SCHEMA


# ---------------------------------------------------------------------------
# Test: Layer 1 - Direct JSON parse (guided decoding)
# ---------------------------------------------------------------------------

class TestLayer1DirectParse:
    """Test direct JSON parsing — the happy path with guided decoding."""

    def test_valid_json(self):
        raw = json.dumps({
            "evidence": "Patient presents with ductal carcinoma",
            "reasoning": "Direct mention in pathology report.",
            "final_output": "Infiltrating duct carcinoma",
            "is_negated": False,
            "date": None,
        })
        result = parse_structured_annotation(raw, used_guided_decoding=True)
        assert result.final_output == "Infiltrating duct carcinoma"
        assert result.evidence == "Patient presents with ductal carcinoma"
        assert result.is_negated is False

    def test_valid_json_with_date(self):
        raw = json.dumps({
            "evidence": "Surgery on 15/01/2024",
            "reasoning": "Date found in text.",
            "final_output": "R0",
            "is_negated": False,
            "date": {
                "date_value": "15/01/2024",
                "source": "extracted_from_text",
            },
        })
        result = parse_structured_annotation(raw, csv_date="01/01/2024")
        assert result.date is not None
        assert result.date.date_value == "15/01/2024"
        assert result.date.source == "extracted_from_text"

    def test_csv_date_applied_when_no_date_in_output(self):
        raw = json.dumps({
            "evidence": "",
            "reasoning": "No date found.",
            "final_output": "Not applicable",
            "is_negated": False,
            "date": None,
        })
        result = parse_structured_annotation(raw, csv_date="10/03/2024")
        assert result.date is not None
        assert result.date.source == "derived_from_csv"
        assert result.date.csv_date == "10/03/2024"

    def test_csv_date_applied_to_derived_date(self):
        raw = json.dumps({
            "evidence": "",
            "reasoning": "No date in note.",
            "final_output": "Grade 2",
            "is_negated": False,
            "date": {
                "date_value": "10/03/2024",
                "source": "derived_from_csv",
            },
        })
        result = parse_structured_annotation(raw, csv_date="10/03/2024")
        assert result.date.csv_date == "10/03/2024"


# ---------------------------------------------------------------------------
# Test: Layer 2 - Thinking block handling
# ---------------------------------------------------------------------------

class TestLayer2ThinkingBlocks:
    """Test extraction from MedGemma thinking blocks."""

    def test_strip_medgemma_thinking(self):
        thinking = "<unused94>Let me think about this...<unused95>"
        json_part = json.dumps({
            "evidence": "test",
            "reasoning": "test",
            "final_output": "result",
            "is_negated": False,
            "date": None,
        })
        raw = thinking + json_part
        result = parse_structured_annotation(raw)
        assert result.final_output == "result"

    def test_unclosed_thinking_with_final_output(self):
        """When thinking block is unclosed (token budget exhausted), try to salvage."""
        raw = '<unused94>The patient has grade 2 tumor. I should output {"final_output": "Grade 2"} as the answer.'
        result = parse_structured_annotation(raw)
        assert result.final_output == "Grade 2"

    def test_unclosed_thinking_with_should_output(self):
        raw = '<unused94>Based on analysis, the output should be "Infiltrating duct carcinoma"'
        result = parse_structured_annotation(raw)
        assert result.final_output == "Infiltrating duct carcinoma"

    def test_strip_xml_thinking(self):
        json_part = json.dumps({
            "evidence": "found in text",
            "reasoning": "clear evidence",
            "final_output": "R1",
            "is_negated": False,
            "date": None,
        })
        raw = f"<unused94>thinking about it</unused94>{json_part}"
        result = parse_structured_annotation(raw)
        assert result.final_output == "R1"


# ---------------------------------------------------------------------------
# Test: Layer 3 - JSON extraction from wrapper text
# ---------------------------------------------------------------------------

class TestLayer3JSONExtraction:
    """Test JSON extraction from markdown blocks and wrapper text."""

    def test_markdown_json_block(self):
        json_obj = {
            "evidence": "biopsy shows grade 1",
            "reasoning": "Direct finding.",
            "final_output": "FNCLCC Grade 1",
            "is_negated": False,
            "date": None,
        }
        raw = f"Here is the annotation:\n```json\n{json.dumps(json_obj)}\n```"
        result = parse_structured_annotation(raw)
        assert result.final_output == "FNCLCC Grade 1"

    def test_json_in_plain_text(self):
        json_obj = {
            "evidence": "noted in report",
            "reasoning": "Clear mention.",
            "final_output": "Positive",
            "is_negated": False,
            "date": None,
        }
        raw = f"Based on analysis:\n{json.dumps(json_obj)}\nEnd of response."
        result = parse_structured_annotation(raw)
        assert result.final_output == "Positive"

    def test_json_array_uses_first(self):
        items = [
            {
                "evidence": "first finding",
                "reasoning": "primary",
                "final_output": "Result A",
                "is_negated": False,
                "date": None,
            },
            {
                "evidence": "second",
                "reasoning": "secondary",
                "final_output": "Result B",
                "is_negated": False,
                "date": None,
            },
        ]
        raw = json.dumps(items)
        # Array gets extracted and first item used
        result = parse_structured_annotation(raw)
        assert result.final_output == "Result A"

    def test_fast_mode_minimal_json(self):
        raw = '{"final_output": "Not applicable"}'
        result = parse_structured_annotation(raw)
        assert result.final_output == "Not applicable"


# ---------------------------------------------------------------------------
# Test: Layer 4 - Regex fallback
# ---------------------------------------------------------------------------

class TestLayer4RegexFallback:
    """Test regex-based extraction from free-form text."""

    def test_annotation_prefix_extraction(self):
        raw = "Evidence: The tumor was 3cm.\nReasoning: Measured directly.\nAnnotation: T2"
        result = parse_structured_annotation(raw)
        assert "T2" in result.final_output

    def test_negation_detection(self):
        raw = "Evidence: no evidence of metastasis.\nFinal output: No metastasis"
        result = parse_structured_annotation(raw)
        assert result.is_negated is True

    def test_date_extraction_from_text(self):
        raw = "The surgery was on 15/03/2024. Final output: R0"
        result = parse_structured_annotation(raw)
        # Date should be extracted but only if no JSON found (regex fallback)
        # Since there's no JSON, regex fallback should find the date
        assert result.final_output is not None


# ---------------------------------------------------------------------------
# Test: Fast mode (only final_output, no evidence/reasoning)
# ---------------------------------------------------------------------------

class TestFastMode:
    """Test fast mode parsing with FastStructuredAnnotation."""

    def test_fast_schema_has_no_evidence_reasoning(self):
        """Fast schema should not include evidence or reasoning fields."""
        schema = FAST_ANNOTATION_JSON_SCHEMA["json_schema"]["schema"]
        props = schema.get("properties", {})
        assert "final_output" in props
        assert "is_negated" in props
        assert "date" in props
        assert "evidence" not in props
        assert "reasoning" not in props

    def test_fast_direct_json_parse(self):
        """Fast mode guided decoding output: only final_output, is_negated, date."""
        raw = json.dumps({
            "final_output": "Infiltrating duct carcinoma",
            "is_negated": False,
            "date": None,
        })
        result = parse_structured_annotation(raw, fast_mode=True, used_guided_decoding=True)
        assert result.final_output == "Infiltrating duct carcinoma"
        assert result.evidence == ""
        assert result.reasoning == "Fast mode: no reasoning requested"
        assert result.is_negated is False

    def test_fast_with_date(self):
        raw = json.dumps({
            "final_output": "R0",
            "is_negated": False,
            "date": {"date_value": "15/01/2024", "source": "extracted_from_text"},
        })
        result = parse_structured_annotation(raw, fast_mode=True)
        assert result.final_output == "R0"
        assert result.date is not None
        assert result.date.date_value == "15/01/2024"

    def test_fast_csv_date_fallback(self):
        raw = json.dumps({
            "final_output": "Grade 2",
            "is_negated": False,
            "date": None,
        })
        result = parse_structured_annotation(raw, csv_date="10/03/2024", fast_mode=True)
        assert result.date is not None
        assert result.date.source == "derived_from_csv"

    def test_fast_placeholder_validator(self):
        raw = json.dumps({
            "final_output": "[select intention]",
            "is_negated": False,
            "date": None,
        })
        result = parse_structured_annotation(raw, fast_mode=True)
        assert result.final_output == "Not applicable"

    def test_fast_ignores_evidence_reasoning_even_if_present(self):
        """In fast mode, extra fields like evidence/reasoning are discarded."""
        raw = json.dumps({
            "evidence": "some evidence",
            "reasoning": "some reasoning",
            "final_output": "Full result",
            "is_negated": False,
            "date": None,
        })
        result = parse_structured_annotation(raw, fast_mode=True)
        assert result.final_output == "Full result"
        # Fast mode discards evidence/reasoning — uses defaults
        assert result.evidence == ""
        assert result.reasoning == "Fast mode: no reasoning requested"

    def test_fast_model_to_structured_annotation(self):
        """FastStructuredAnnotation.to_structured_annotation() conversion."""
        fast_ann = FastStructuredAnnotation(
            final_output="Test output",
            is_negated=True,
            date=None,
        )
        full = fast_ann.to_structured_annotation()
        assert isinstance(full, StructuredAnnotation)
        assert full.final_output == "Test output"
        assert full.is_negated is True
        assert full.evidence == ""
        assert full.reasoning == "Fast mode: no reasoning requested"

    def test_fast_markdown_extraction(self):
        """Fast mode JSON inside markdown block."""
        json_obj = {
            "final_output": "FNCLCC Grade 1",
            "is_negated": False,
            "date": None,
        }
        raw = f"```json\n{json.dumps(json_obj)}\n```"
        result = parse_structured_annotation(raw, fast_mode=True)
        assert result.final_output == "FNCLCC Grade 1"
        assert result.evidence == ""


# ---------------------------------------------------------------------------
# Test: Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Test that legacy entry points still work."""

    def test_generate_structured_annotation_fallback(self):
        raw = json.dumps({
            "evidence": "test",
            "reasoning": "test",
            "final_output": "legacy result",
            "is_negated": False,
            "date": None,
        })
        result = generate_structured_annotation_fallback(
            prompt="test prompt",
            raw_output=raw,
            csv_date=None,
        )
        assert result.final_output == "legacy result"


# ---------------------------------------------------------------------------
# Test: Helper functions
# ---------------------------------------------------------------------------

class TestHelperFunctions:
    """Test internal helper functions."""

    def test_strip_thinking_blocks_medgemma(self):
        raw = "<unused94>thinking...<unused95>actual response"
        cleaned = _strip_thinking_blocks(raw)
        assert "<unused" not in cleaned

    def test_strip_thinking_blocks_xml(self):
        raw = "<unused94>thinking</unused94>actual response"
        cleaned = _strip_thinking_blocks(raw)
        assert "actual response" in cleaned

    def test_strip_thinking_blocks_no_thinking(self):
        raw = "just a normal response"
        cleaned = _strip_thinking_blocks(raw)
        assert cleaned == raw

    def test_extract_json_string_markdown(self):
        json_obj = {"evidence": "test", "reasoning": "test", "final_output": "result", "is_negated": False}
        raw = f"```json\n{json.dumps(json_obj)}\n```"
        extracted = _extract_json_string(raw)
        assert extracted is not None
        parsed = json.loads(extracted)
        assert parsed["final_output"] == "result"

    def test_extract_json_string_none_for_plain_text(self):
        raw = "This is just plain text with no JSON"
        extracted = _extract_json_string(raw)
        assert extracted is None


# ---------------------------------------------------------------------------
# Test: Per-prompt schema generation (enum-constrained final_output)
# ---------------------------------------------------------------------------

class TestPerPromptSchema:
    """Test per-prompt schema generation with enum constraints."""

    def test_simple_enum_prompt(self):
        """Prompt with all fields having value_code_mappings → constrained schema."""
        entity_mapping = {
            "field_mappings": [{
                "field_name": "marginsAfterSurgery",
                "value_code_mappings": {"R0": "1634643", "R1": "1633801", "R2": "1634484"},
            }]
        }
        schema = build_per_prompt_schema(entity_mapping)
        assert schema is not None
        assert schema["type"] == "json_schema"
        enum_values = schema["json_schema"]["schema"]["properties"]["final_output"]["enum"]
        assert "R0" in enum_values
        assert "R1" in enum_values
        assert "R2" in enum_values
        assert "Not applicable" in enum_values
        assert len(enum_values) == 4  # R0, R1, R2 + Not applicable

    def test_template_prompt_returns_none(self):
        """Prompt with unconstrained fields (date, free text) → None."""
        entity_mapping = {
            "field_mappings": [
                {"field_name": "intent", "value_code_mappings": {"curative": "1", "palliative": "2"}},
                {"field_name": "startDate"},  # No value_code_mappings → unconstrained
            ]
        }
        schema = build_per_prompt_schema(entity_mapping)
        assert schema is None

    def test_no_entity_mapping_returns_none(self):
        """No entity_mapping → None."""
        assert build_per_prompt_schema(None) is None
        assert build_per_prompt_schema({}) is None

    def test_empty_field_mappings_returns_none(self):
        """Empty field_mappings list → None."""
        schema = build_per_prompt_schema({"field_mappings": []})
        assert schema is None

    def test_multi_field_all_constrained(self):
        """Multiple field_mappings all with value_code_mappings → constrained."""
        entity_mapping = {
            "field_mappings": [
                {
                    "field_name": "localised",
                    "value_code_mappings": {
                        "Stage at diagnosis: localized.": False,
                        "Stage at diagnosis: loco-regional.": False,
                    },
                },
                {
                    "field_name": "locoRegional",
                    "value_code_mappings": {
                        "Stage at diagnosis: loco-regional.": True,
                    },
                },
            ]
        }
        schema = build_per_prompt_schema(entity_mapping)
        assert schema is not None
        enum_values = schema["json_schema"]["schema"]["properties"]["final_output"]["enum"]
        assert "Stage at diagnosis: localized." in enum_values
        assert "Stage at diagnosis: loco-regional." in enum_values
        assert "Not applicable" in enum_values

    def test_fast_mode_uses_fast_base_schema(self):
        """Fast mode schema should NOT have evidence/reasoning fields."""
        entity_mapping = {
            "field_mappings": [{
                "field_name": "status",
                "value_code_mappings": {"NED": "1", "AWD": "2"},
            }]
        }
        schema = build_per_prompt_schema(entity_mapping, fast_mode=True)
        assert schema is not None
        props = schema["json_schema"]["schema"]["properties"]
        assert "evidence" not in props
        assert "reasoning" not in props
        assert "final_output" in props
        assert "is_negated" in props
        enum_values = props["final_output"]["enum"]
        assert "NED" in enum_values
        assert "Not applicable" in enum_values

    def test_standard_mode_has_all_fields(self):
        """Standard mode schema should have evidence/reasoning fields."""
        entity_mapping = {
            "field_mappings": [{
                "field_name": "status",
                "value_code_mappings": {"NED": "1", "AWD": "2"},
            }]
        }
        schema = build_per_prompt_schema(entity_mapping, fast_mode=False)
        assert schema is not None
        props = schema["json_schema"]["schema"]["properties"]
        assert "evidence" in props
        assert "reasoning" in props
        assert "final_output" in props

    def test_not_applicable_always_last(self):
        """'Not applicable' should be the last enum value."""
        entity_mapping = {
            "field_mappings": [{
                "field_name": "gender",
                "value_code_mappings": {"male": "1", "female": "2"},
            }]
        }
        schema = build_per_prompt_schema(entity_mapping)
        enum_values = schema["json_schema"]["schema"]["properties"]["final_output"]["enum"]
        assert enum_values[-1] == "Not applicable"

    def test_get_prompt_schema_constrained(self):
        """get_prompt_schema returns constrained schema for enum prompts."""
        entity_mapping = {
            "field_mappings": [{
                "field_name": "margins",
                "value_code_mappings": {"R0": "1", "R1": "2"},
            }]
        }
        schema = get_prompt_schema("test_enum", entity_mapping, fast_mode=False)
        assert "enum" in schema["json_schema"]["schema"]["properties"]["final_output"]

    def test_get_prompt_schema_fallback_generic(self):
        """get_prompt_schema returns generic schema for free-text prompts."""
        schema = get_prompt_schema("test_free", None, fast_mode=False)
        assert schema == ANNOTATION_JSON_SCHEMA

    def test_get_prompt_schema_fallback_fast(self):
        """get_prompt_schema returns fast generic schema in fast mode."""
        schema = get_prompt_schema("test_free_fast", None, fast_mode=True)
        assert schema == FAST_ANNOTATION_JSON_SCHEMA

    def test_enum_constrained_parsing(self):
        """Verify parse_structured_annotation works with enum-valid values."""
        raw = json.dumps({
            "evidence": "Margins clear",
            "reasoning": "R0 resection confirmed",
            "final_output": "R0",
            "is_negated": False,
            "date": None,
        })
        result = parse_structured_annotation(raw, used_guided_decoding=True)
        assert result.final_output == "R0"

    def test_schema_does_not_mutate_base(self):
        """Building constrained schemas should not mutate the base model schema."""
        original_schema = StructuredAnnotation.model_json_schema()
        assert "enum" not in original_schema["properties"]["final_output"]

        entity_mapping = {
            "field_mappings": [{
                "field_name": "test",
                "value_code_mappings": {"A": "1", "B": "2"},
            }]
        }
        build_per_prompt_schema(entity_mapping, fast_mode=False)

        # Verify base schema was not mutated
        assert "enum" not in original_schema["properties"]["final_output"]
        fresh_schema = StructuredAnnotation.model_json_schema()
        assert "enum" not in fresh_schema["properties"]["final_output"]


# ---------------------------------------------------------------------------
# Test: Prompt wrapper JSON example stripping
# ---------------------------------------------------------------------------

class TestPromptWrapperJSONStripping:
    """Test that wrap_prompt_with_json_format strips trailing JSON examples."""

    TEMPLATE_WITH_JSON_EXAMPLE = (
        'Task: Extract tumor site.\n\n'
        '### Input:\n'
        '- Medical Note: "{{note_original_text}}"\n\n'
        '### Response (JSON only):\n'
        '{\n'
        '  "evidence": "exact literal quote from the note that supports this annotation",\n'
        '  "reasoning": "brief clinical validation and inference logic (2-3 sentences max)",\n'
        '  "final_output": "annotation in the exact format specified above",\n'
        '  "is_negated": false,\n'
        '  "date": {"date_value": "DD/MM/YYYY", "source": "extracted_from_text or derived_from_csv"}\n'
        '}'
    )

    TEMPLATE_WITHOUT_JSON_EXAMPLE = (
        'Task: Extract tumor site.\n\n'
        '### Input:\n'
        '- Medical Note: "{{note_original_text}}"\n\n'
        '### Response:'
    )

    def test_guided_strips_json_example(self):
        """Guided decoding mode should strip the trailing JSON example block."""
        from lib.prompt_wrapper import wrap_prompt_with_json_format
        result = wrap_prompt_with_json_format(
            self.TEMPLATE_WITH_JSON_EXAMPLE, use_guided_decoding=True
        )
        assert '"annotation in the exact format specified above"' not in result
        assert '### Response (JSON only, no other text):' in result

    def test_nonguided_strips_json_example(self):
        """Non-guided mode should also strip the trailing JSON example block."""
        from lib.prompt_wrapper import wrap_prompt_with_json_format
        result = wrap_prompt_with_json_format(
            self.TEMPLATE_WITH_JSON_EXAMPLE, use_guided_decoding=False
        )
        assert '"annotation in the exact format specified above"' not in result
        assert '### Response (JSON only, no other text):' in result

    def test_no_double_replacement(self):
        """Should not produce garbled headers like '### Response (JSON only, no other text) (JSON only):'."""
        from lib.prompt_wrapper import wrap_prompt_with_json_format
        result = wrap_prompt_with_json_format(
            self.TEMPLATE_WITH_JSON_EXAMPLE, use_guided_decoding=True
        )
        assert '(JSON only, no other text) (JSON only)' not in result

    def test_template_without_json_example_still_works(self):
        """Templates that don't have a JSON example should still get the Response header."""
        from lib.prompt_wrapper import wrap_prompt_with_json_format
        result = wrap_prompt_with_json_format(
            self.TEMPLATE_WITHOUT_JSON_EXAMPLE, use_guided_decoding=True
        )
        assert '### Response (JSON only, no other text):' in result

    def test_guided_inserts_concise_instructions(self):
        """Guided mode should insert concise format instructions."""
        from lib.prompt_wrapper import wrap_prompt_with_json_format
        result = wrap_prompt_with_json_format(
            self.TEMPLATE_WITH_JSON_EXAMPLE, use_guided_decoding=True
        )
        assert '# Output Format' in result

    def test_nonguided_inserts_full_instructions(self):
        """Non-guided mode should insert full format instructions."""
        from lib.prompt_wrapper import wrap_prompt_with_json_format
        result = wrap_prompt_with_json_format(
            self.TEMPLATE_WITH_JSON_EXAMPLE, use_guided_decoding=False
        )
        assert '# Output Format (JSON)' in result
