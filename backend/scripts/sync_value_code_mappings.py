"""
Sync value_code_mappings from latest_prompts → fast_prompts for all centers,
and add INT mappings to VGR (which has none).

Strategy: match field_mappings entries by template_placeholder within the same variable key.
"""
import json
from pathlib import Path

BASE = Path(__file__).parent.parent / "data"
LATEST = BASE / "latest_prompts"
FAST   = BASE / "fast_prompts"


def load(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def save(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Saved: {path}")


def get_mappings_index(prompts: dict) -> dict[str, dict[str, dict]]:
    """
    Returns {variable_key: {template_placeholder: value_code_mappings}}
    for all field_mappings entries that have value_code_mappings.
    """
    index: dict[str, dict[str, dict]] = {}
    for var_key, var_data in prompts.items():
        em = var_data.get("entity_mapping", {})
        for fm in em.get("field_mappings", []):
            vcm = fm.get("value_code_mappings")
            if vcm is not None:
                placeholder = fm["template_placeholder"]
                index.setdefault(var_key, {})[placeholder] = vcm
    return index


def apply_mappings(target: dict, mappings_index: dict, label: str) -> int:
    """
    Apply mappings_index onto target prompts dict.
    Only touches variables that exist in target AND in mappings_index.
    Returns count of field_mapping entries updated.
    """
    updated = 0
    for var_key, placeholder_map in mappings_index.items():
        if var_key not in target:
            continue
        em = target[var_key].get("entity_mapping", {})
        for fm in em.get("field_mappings", []):
            placeholder = fm["template_placeholder"]
            if placeholder in placeholder_map:
                old = fm.get("value_code_mappings")
                fm["value_code_mappings"] = placeholder_map[placeholder]
                if old != placeholder_map[placeholder]:
                    print(f"    [{label}] {var_key}.{fm['field_name']} ({placeholder}): "
                          f"{'added' if old is None else 'updated'} "
                          f"({len(placeholder_map[placeholder])} entries)")
                    updated += 1
    return updated


def sync(source_path: Path, target_path: Path, label: str) -> None:
    print(f"\n--- {label} ---")
    source = load(source_path)
    target = load(target_path)
    idx = get_mappings_index(source)
    n = apply_mappings(target, idx, label)
    if n == 0:
        print(f"  Nothing to update (already in sync or no shared variables with mappings)")
    else:
        save(target_path, target)
        print(f"  Total: {n} field_mapping(s) updated")


if __name__ == "__main__":
    # 1. latest_INT-SARC → fast_INT-SARC
    sync(
        LATEST / "INT-SARC" / "prompts.json",
        FAST   / "INT-SARC" / "prompts.json",
        "latest_INT-SARC → fast_INT-SARC",
    )

    # 2. latest_MSCI → fast_MSCI
    sync(
        LATEST / "MSCI" / "prompts.json",
        FAST   / "MSCI" / "prompts.json",
        "latest_MSCI → fast_MSCI",
    )

    # 3. latest_INT-SARC → latest_VGR  (add INT mappings for shared variables)
    sync(
        LATEST / "INT"  / "prompts.json",
        LATEST / "VGR"  / "prompts.json",
        "latest_INT-SARC → latest_VGR",
    )

    # 4. latest_INT-SARC → fast_VGR
    sync(
        LATEST / "INT"  / "prompts.json",
        FAST   / "VGR"  / "prompts.json",
        "latest_INT-SARC → fast_VGR",
    )

    print("\nDone.")
