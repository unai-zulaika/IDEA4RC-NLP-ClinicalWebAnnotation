"""Tests for multi-center prompt loading in prompt_adapter.py"""

import json
import tempfile
from pathlib import Path

import pytest

from lib.prompt_adapter import adapt_all_prompts, adapt_all_prompts_from_dir, adapt_int_prompts


@pytest.fixture
def prompts_file(tmp_path: Path) -> Path:
    """Create a minimal prompts.json with multiple centers."""
    data = {
        "INT": {
            "biopsygrading-int": {
                "template": "INT biopsy template: {{note_original_text}}",
                "entity_mapping": {},
            },
            "surgerymargins-int": {
                "template": "INT margins template: {{note_original_text}}",
            },
        },
        "MSCI": {
            "biopsygrading-msci": {
                "template": "MSCI biopsy template: {{note_original_text}}",
            },
        },
        "VGR": {
            "biopsygrading-vgr": "VGR biopsy template: {{note_original_text}}",
        },
    }
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_adapt_all_prompts_returns_all_centers(prompts_file: Path):
    """adapt_all_prompts should load prompts from every center."""
    result = adapt_all_prompts(prompts_file)

    assert "biopsygrading-int" in result
    assert "surgerymargins-int" in result
    assert "biopsygrading-msci" in result
    assert "biopsygrading-vgr" in result
    assert len(result) == 4


def test_adapt_all_prompts_placeholder_replacement(prompts_file: Path):
    """Placeholder {{note_original_text}} should be replaced with {note}."""
    result = adapt_all_prompts(prompts_file)

    for key, value in result.items():
        template = value["template"]
        assert "{{note_original_text}}" not in template, f"{key} still has old placeholder"
        assert "{note}" in template, f"{key} missing {{note}} placeholder"


def test_adapt_int_prompts_is_backward_compat_alias(prompts_file: Path):
    """adapt_int_prompts should return the same result as adapt_all_prompts."""
    all_result = adapt_all_prompts(prompts_file)
    int_result = adapt_int_prompts(prompts_file)

    assert all_result == int_result


def test_adapt_all_prompts_empty_file(tmp_path: Path):
    """Should raise ValueError when no prompts found."""
    path = tmp_path / "empty.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="No prompts found"):
        adapt_all_prompts(path)


def test_adapt_all_prompts_with_real_file():
    """Smoke test against the actual prompts.json if it exists."""
    real_path = Path(__file__).resolve().parent.parent / "data" / "prompts" / "prompts.json"
    if not real_path.exists():
        pytest.skip("Real prompts.json not found")

    # Load raw data to know expected counts per center
    with open(real_path, encoding="utf-8") as f:
        raw = json.load(f)

    result = adapt_all_prompts(real_path)

    # Collect all unique keys across centers (some keys may overlap between centers)
    all_unique_keys: set[str] = set()
    for center_data in raw.values():
        if isinstance(center_data, dict):
            all_unique_keys.update(center_data.keys())

    assert len(result) == len(all_unique_keys), (
        f"Expected {len(all_unique_keys)} unique prompts, got {len(result)}"
    )

    # INT prompts (suffixed with -int) should be present
    int_keys = [k for k in result if k.endswith("-int")]
    assert len(int_keys) > 0, "Expected INT prompts"

    # Every prompt key from every center should appear in the result
    for center_name in ("MSCI", "VGR"):
        center_prompt_keys = set(raw.get(center_name, {}).keys())
        loaded_keys = set(result.keys())
        assert center_prompt_keys.issubset(loaded_keys), (
            f"{center_name} prompts missing from result: "
            f"{center_prompt_keys - loaded_keys}"
        )


def test_adapt_all_prompts_with_real_directory():
    """Smoke test against the actual latest_prompts/ directory if it exists."""
    real_dir = Path(__file__).resolve().parent.parent / "data" / "latest_prompts"
    if not real_dir.is_dir():
        pytest.skip("Real latest_prompts/ directory not found")

    result = adapt_all_prompts(real_dir)
    assert len(result) > 0, "Expected prompts from directory"

    # Keys should be suffixed with center names
    centers = [d.name.lower() for d in real_dir.iterdir() if d.is_dir()]
    for key in result:
        has_suffix = any(key.endswith(f"-{c}") for c in centers)
        assert has_suffix, f"Key '{key}' missing center suffix"
