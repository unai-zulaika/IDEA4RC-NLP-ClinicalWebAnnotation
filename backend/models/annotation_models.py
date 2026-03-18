"""
Pydantic models for structured annotation output.

Used both for:
1. JSON Schema generation (via model_json_schema()) for vLLM guided decoding
2. Validation of LLM output after generation
"""
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal


class HallucinationFlag(BaseModel):
    """Flag indicating a detected hallucination pattern in LLM output."""
    type: str = Field(..., description="Hallucination type, e.g. 'repetition_loop'")
    field: str = Field(..., description="Which field triggered the flag: 'reasoning' or 'raw_output'")
    severity: Literal["medium", "high"] = Field(..., description="Severity level")
    duplicate_ratio: float = Field(..., description="Fraction of sentences that are duplicates (0.0–1.0)")
    message: str = Field(..., description="Human-readable description of the detected issue")


class AnnotationDateInfo(BaseModel):
    """Information about the date in the annotation"""
    date_value: Optional[str] = Field(
        None,
        description="The date value if present in the annotation (e.g., '12/01/2024', '2024-01-12')"
    )
    source: Literal["extracted_from_text", "derived_from_csv"] = Field(
        ...,
        description="Whether the date was extracted from the note text or derived from the CSV date column"
    )
    csv_date: Optional[str] = Field(
        None,
        description="The date from the CSV if source is 'derived_from_csv'"
    )


class StructuredAnnotation(BaseModel):
    """Structured annotation output from LLM.

    Used for vLLM guided decoding (response_format with json_schema)
    and for validation of raw LLM output via fallback parsing.
    """
    reasoning: str = Field(
        "",
        description="Clinical reasoning explaining the logic used to derive the annotation. Include validation (current vs PMH vs suspicion), inference steps, and reference the specific phrases from the note that support the conclusion."
    )
    final_output: str = Field(
        ...,
        description="The final annotation text following the exact template format specified in the prompt. If the required information is not available in the note, use an empty string '' or a standard phrase like 'Unknown', 'Not available', 'Not specified', or 'Information not available in the note'."
    )
    is_negated: bool = Field(
        False,
        description="Whether any of the values filled in within the templates are negated (e.g., 'no evidence of disease', 'absence of', 'ruled out', etc.)"
    )
    date: Optional[AnnotationDateInfo] = Field(
        None,
        description="Date information: either extracted from the text or derived from the CSV date column. Only include if the annotation contains date-related information."
    )

    @field_validator('final_output')
    @classmethod
    def final_output_not_placeholder(cls, v: str) -> str:
        """Strip template placeholders from final_output.

        Instead of replacing the entire output with 'Not applicable' when a
        placeholder is detected, strip the placeholder text and keep the
        surrounding annotation.  Only return 'Not applicable' when nothing
        meaningful remains after stripping.
        """
        import re
        # Strip bracketed placeholder patterns (with optional surrounding parens)
        _placeholder_re = r'\s*\(?\[(?:select|put|choose|provide)[^\]]*\]\)?'
        _generic_re = r'\[(?:value|date|select)\]'
        had_placeholder = bool(
            re.search(_placeholder_re, v, re.IGNORECASE)
            or re.search(_generic_re, v, re.IGNORECASE)
        )
        if not had_placeholder:
            return v  # No placeholders found — return as-is

        stripped = re.sub(_placeholder_re, '', v, flags=re.IGNORECASE)
        stripped = re.sub(_generic_re, '', stripped, flags=re.IGNORECASE)
        # Clean up residual whitespace before punctuation
        stripped = re.sub(r'\s+\.', '.', stripped)
        stripped = stripped.strip()

        # If nothing meaningful remains, it was entirely a placeholder.
        # Also detect bare labels like "Grade:" left after stripping the
        # value portion (e.g. "Grade: [select value]" → "Grade:").
        cleaned = stripped.rstrip('.:, ').strip()
        if not cleaned:
            return "Not applicable"
        # Check for "Label:" pattern where everything after the colon was
        # a placeholder (nothing meaningful after the last colon).
        if ':' in stripped:
            after_colon = stripped.rsplit(':', 1)[1].strip().rstrip('., ')
            if not after_colon:
                return "Not applicable"
        return stripped

    @field_validator('reasoning')
    @classmethod
    def reasoning_max_length(cls, v: str) -> str:
        """Truncate excessively long reasoning to save context."""
        if len(v) > 2000:
            return v[:1997] + "..."
        return v


class FastStructuredAnnotation(BaseModel):
    """Minimal annotation output for fast mode.

    Only requires final_output to minimize token usage.
    Used for vLLM guided decoding in fast mode.
    """
    final_output: str = Field(
        ...,
        description="The final annotation text following the exact template format specified in the prompt. If the required information is not available in the note, use 'Not applicable'."
    )
    is_negated: bool = Field(
        False,
        description="Whether the annotation indicates absence or negation"
    )
    date: Optional[AnnotationDateInfo] = Field(
        None,
        description="Date information extracted from note or CSV"
    )

    @field_validator('final_output')
    @classmethod
    def final_output_not_placeholder(cls, v: str) -> str:
        """Strip template placeholders from final_output.

        Instead of replacing the entire output with 'Not applicable' when a
        placeholder is detected, strip the placeholder text and keep the
        surrounding annotation.  Only return 'Not applicable' when nothing
        meaningful remains after stripping.
        """
        import re
        _placeholder_re = r'\s*\(?\[(?:select|put|choose|provide)[^\]]*\]\)?'
        _generic_re = r'\[(?:value|date|select)\]'
        had_placeholder = bool(
            re.search(_placeholder_re, v, re.IGNORECASE)
            or re.search(_generic_re, v, re.IGNORECASE)
        )
        if not had_placeholder:
            return v

        stripped = re.sub(_placeholder_re, '', v, flags=re.IGNORECASE)
        stripped = re.sub(_generic_re, '', stripped, flags=re.IGNORECASE)
        stripped = re.sub(r'\s+\.', '.', stripped)
        stripped = stripped.strip()

        cleaned = stripped.rstrip('.:, ').strip()
        if not cleaned:
            return "Not applicable"
        if ':' in stripped:
            after_colon = stripped.rsplit(':', 1)[1].strip().rstrip('., ')
            if not after_colon:
                return "Not applicable"
        return stripped

    def to_structured_annotation(self) -> "StructuredAnnotation":
        """Convert to full StructuredAnnotation for downstream compatibility."""
        return StructuredAnnotation(
            reasoning="Fast mode: no reasoning requested",
            final_output=self.final_output,
            is_negated=self.is_negated,
            date=self.date,
        )

