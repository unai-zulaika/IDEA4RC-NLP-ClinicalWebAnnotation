"""Tests for directory-based prompt loading and key suffixing."""

import json
from pathlib import Path

import pytest

from lib.prompt_adapter import adapt_all_prompts, adapt_all_prompts_from_dir


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    """Create a minimal directory-based prompt structure."""
    for center, prompts in {
        "INT": {
            "biopsygrading": {
                "template": "INT biopsy template: {{note_original_text}}",
                "entity_mapping": {},
            },
            "surgerymargins": {
                "template": "INT margins template: {{note_original_text}}",
            },
        },
        "MSCI": {
            "biopsygrading": {
                "template": "MSCI biopsy template: {{note_original_text}}",
            },
        },
        "VGR": {
            "biopsygrading": "VGR biopsy template: {{note_original_text}}",
        },
    }.items():
        center_dir = tmp_path / center
        center_dir.mkdir()
        (center_dir / "prompts.json").write_text(
            json.dumps(prompts), encoding="utf-8"
        )
    return tmp_path


def test_load_from_dir_suffixes_keys(prompts_dir: Path):
    """Keys should be suffixed with -center_lower when loaded from directory."""
    result = adapt_all_prompts_from_dir(prompts_dir)

    assert "biopsygrading-int" in result
    assert "surgerymargins-int" in result
    assert "biopsygrading-msci" in result
    assert "biopsygrading-vgr" in result
    assert len(result) == 4


def test_load_from_dir_no_collisions(prompts_dir: Path):
    """Same unsuffixed key in different centers should not collide."""
    result = adapt_all_prompts_from_dir(prompts_dir)

    # All three centers have "biopsygrading", but suffixed differently
    assert result["biopsygrading-int"]["template"] != result["biopsygrading-msci"]["template"]
    assert result["biopsygrading-int"]["template"] != result["biopsygrading-vgr"]["template"]


def test_placeholder_replacement(prompts_dir: Path):
    """{{note_original_text}} should be replaced with {note}."""
    result = adapt_all_prompts_from_dir(prompts_dir)

    for key, value in result.items():
        template = value["template"]
        assert "{{note_original_text}}" not in template, f"{key} still has old placeholder"
        assert "{note}" in template, f"{key} missing {{note}} placeholder"


def test_adapt_all_prompts_accepts_directory(prompts_dir: Path):
    """adapt_all_prompts() should detect a directory and delegate to from_dir."""
    result = adapt_all_prompts(prompts_dir)

    assert "biopsygrading-int" in result
    assert "biopsygrading-msci" in result
    assert len(result) == 4


def test_empty_directory_raises_error(tmp_path: Path):
    """Should raise ValueError when no center subdirs exist."""
    with pytest.raises(ValueError, match="No center subdirectories"):
        adapt_all_prompts_from_dir(tmp_path)


def test_nonexistent_directory_raises_error(tmp_path: Path):
    """Should raise ValueError for nonexistent path."""
    with pytest.raises(ValueError, match="not found"):
        adapt_all_prompts_from_dir(tmp_path / "does_not_exist")


def test_load_and_save_roundtrip(prompts_dir: Path, tmp_path: Path):
    """Load from directory, save back, and reload should give same result."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    # Simulate the save logic from prompts.py
    from lib.prompt_adapter import adapt_all_prompts_from_dir

    # First load raw (unsuffixed) data, suffix it, then strip and write back
    result_dir = tmp_path / "roundtrip"
    result_dir.mkdir()

    # Load suffixed prompts
    adapted = adapt_all_prompts_from_dir(prompts_dir)

    # Reconstruct per-center with suffixed keys (simulating load_prompts_json)
    centers = {}
    for center_name in ("INT", "MSCI", "VGR"):
        center_lower = center_name.lower()
        center_prompts = {}
        for key, _val in adapted.items():
            if key.endswith(f"-{center_lower}"):
                # Read from original dir for full data (adapted only has template)
                orig_file = prompts_dir / center_name / "prompts.json"
                if orig_file.exists():
                    orig_data = json.loads(orig_file.read_text())
                    unsuffixed = key[: -len(f"-{center_lower}")]
                    if unsuffixed in orig_data:
                        center_prompts[key] = orig_data[unsuffixed]
        centers[center_name] = center_prompts

    # Save (strip suffixes)
    for center, center_prompts in centers.items():
        center_lower = center.lower()
        suffix = f"-{center_lower}"
        raw_prompts = {}
        for k, v in center_prompts.items():
            raw_key = k[: -len(suffix)] if k.endswith(suffix) else k
            raw_prompts[raw_key] = v

        out_dir = result_dir / center
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "prompts.json").write_text(
            json.dumps(raw_prompts, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Reload and compare
    reloaded = adapt_all_prompts_from_dir(result_dir)
    assert set(reloaded.keys()) == set(adapted.keys())


def test_smoke_real_latest_prompts():
    """Smoke test against the actual latest_prompts/ directory if it exists."""
    real_dir = Path(__file__).resolve().parent.parent / "data" / "latest_prompts"
    if not real_dir.is_dir():
        pytest.skip("Real latest_prompts/ directory not found")

    result = adapt_all_prompts_from_dir(real_dir)

    # Should have prompts from all centers
    assert len(result) > 0

    # All keys should be suffixed
    centers = [d.name.lower() for d in real_dir.iterdir() if d.is_dir()]
    for key in result:
        has_suffix = any(key.endswith(f"-{c}") for c in centers)
        assert has_suffix, f"Key '{key}' is not suffixed with any center: {centers}"

    # Each template should have {note} placeholder (from adaptation)
    for key, value in result.items():
        template = value["template"]
        assert "{{note_original_text}}" not in template, f"{key} still has old placeholder"
