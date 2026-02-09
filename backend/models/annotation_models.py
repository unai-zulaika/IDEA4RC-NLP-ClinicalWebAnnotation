"""
Pydantic models for structured annotation output using Outlines
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date as date_type


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
    """Structured annotation output from LLM using Outlines"""
    evidence: str = Field(
        ...,
        description="The exact literal phrase or sentence from the note that supports this annotation. This will be used to highlight evidence in the text."
    )
    reasoning: str = Field(
        ...,
        description="Explanation of the logic used to map the natural language to the standard value. Include clinical validation (current vs PMH vs suspicion) and inference steps."
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

