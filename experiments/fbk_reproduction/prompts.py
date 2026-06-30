"""Per-variable prompt templates matching FBK's slide-11 strict format.

FBK uses a single short task description per variable, a strict output format,
and explicitly tells the model: 'Do not include any explanations, reasoning,
extra text, the medical note — only output the annotation value in the
specified format above.'

These templates mirror that style. They take a list of few-shot examples
(retrieved by RAG, see rag_retriever.py) and the input note's original text.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VariableSpec:
    name: str
    task: str
    output_format: str
    unknown_template: str


VARIABLES: dict[str, VariableSpec] = {
    "biopsy_mitotic_count": VariableSpec(
        name="biopsy_mitotic_count",
        task=(
            "You are an expert medical annotator specializing in extracting "
            "structured clinical information from oncology notes. Identify the "
            "biopsy mitotic count from the provided medical note and output it "
            "exactly in the following format:"
        ),
        output_format="Biopsy mitotic count: [value]HPF/mm2.",
        unknown_template='"Unknown biopsy mitotic count."',
    ),
    "necrosis_in_biopsy": VariableSpec(
        name="necrosis_in_biopsy",
        task=(
            "You are an expert medical annotator specializing in extracting "
            "structured clinical information from oncology notes. Identify whether "
            "necrosis is present in the biopsy specimen and output it exactly in "
            "the following format:"
        ),
        output_format="Necrosis in biopsy specimen (type of): [absent | present].",
        unknown_template='"Unknown necrosis status in biopsy."',
    ),
    "necrosis_in_surgical": VariableSpec(
        name="necrosis_in_surgical",
        task=(
            "You are an expert medical annotator specializing in extracting "
            "structured clinical information from oncology notes. Identify whether "
            "necrosis is present in the surgical specimen and output it exactly in "
            "the following format:"
        ),
        output_format="Necrosis in surgical specimen (type of): [absent | present].",
        unknown_template='"Unknown necrosis status in surgical specimen."',
    ),
    "patient_weight_height": VariableSpec(
        name="patient_weight_height",
        task=(
            "You are an expert medical annotator specializing in extracting "
            "structured clinical information from oncology notes. Identify the "
            "patient's weight and height (and evaluation date if present) and "
            "output it exactly in the following format:"
        ),
        output_format=(
            "Patient's weight [value]kg and height [value]cm "
            "(evaluated on DD/MM/YYYY)."
        ),
        unknown_template='"Unknown weight and height."',
    ),
}


def render_prompt(
    variable: str,
    note_text: str,
    few_shots: list[tuple[str, str]],
) -> str:
    """Build the full strict-format prompt for a variable.

    few_shots: list of (note_text, gold_annotation) pairs.
    """
    spec = VARIABLES[variable]
    examples = []
    for i, (note, ann) in enumerate(few_shots, start=1):
        examples.append(
            f"Example {i}:\n"
            f"### Input:\n"
            f"- Medical Note: \"{note}\"\n"
            f"### Response:\n"
            f"Annotation: {ann}"
        )
    examples_block = "\n\n".join(examples) if examples else "(no examples)"

    return (
        f"Task: {spec.task}\n\n"
        f"Format:\n"
        f"{spec.output_format}\n"
        f"(If not explicitly stated or unclear, output: {spec.unknown_template})\n\n"
        f"Do not include any explanations, reasoning, extra text, the medical "
        f"note — only output the annotation value in the specified format above.\n\n"
        f"Here are few examples for your understanding:\n\n"
        f"{examples_block}\n\n"
        f"Now process the following note in the same way:\n\n"
        f"### Input:\n"
        f"- Medical Note: \"{note_text}\"\n"
        f"### Response:\n"
        f"Annotation:"
    )
