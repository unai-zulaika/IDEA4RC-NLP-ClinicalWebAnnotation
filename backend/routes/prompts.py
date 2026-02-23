"""
Prompt management routes
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Optional, Tuple, Union
from pathlib import Path
import json
import sys

# Import from local lib directory
try:
    from lib.prompt_adapter import adapt_int_prompts
except ImportError as e:
    raise ImportError(f"Could not import prompt_adapter from lib: {e}")
from models.schemas import PromptInfo, PromptUpdate, PromptRename, EntityMapping, CenterCreate

router = APIRouter()

DEFAULT_CENTER = "INT"


def get_latest_prompts_dir() -> Path:
    """Get path to the latest_prompts directory (directory-based prompt storage)."""
    backend_dir = Path(__file__).parent.parent
    return backend_dir / "data" / "latest_prompts"


def load_prompts_json() -> Dict:
    """
    Load prompts from the directory-based structure.

    Iterates over center subdirectories in latest_prompts/, loads each
    {CENTER}/prompts.json, and suffixes keys with -{center_lower} to
    maintain uniqueness in the flat dict.

    Returns:
        Dict with shape {center: {suffixed_key: prompt_data}}
        e.g. {"INT": {"biopsygrading-int": {...}}, "VGR": {"biopsygrading-vgr": {...}}}
    """
    prompts_dir = get_latest_prompts_dir()
    if not prompts_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Prompts directory not found: {prompts_dir}")

    result: Dict[str, Dict] = {}
    center_dirs = sorted(
        [d for d in prompts_dir.iterdir() if d.is_dir() and (d / "prompts.json").exists()]
    )

    if not center_dirs:
        raise HTTPException(status_code=404, detail=f"No center directories found in {prompts_dir}")

    for center_dir in center_dirs:
        center = center_dir.name  # e.g. "INT"
        center_lower = center.lower()
        prompts_file = center_dir / "prompts.json"

        with open(prompts_file, 'r', encoding='utf-8') as f:
            raw_prompts = json.load(f)

        # Suffix keys with -center_lower
        suffixed: Dict = {}
        for key, value in raw_prompts.items():
            suffixed[f"{key}-{center_lower}"] = value

        result[center] = suffixed

    return result


def _extract_template_and_mapping(prompt_data) -> Tuple[str, Optional[EntityMapping]]:
    """Extract template and mapping from prompt data (supports both old string format and new object format)"""
    if isinstance(prompt_data, str):
        # Old format: just a string template
        return prompt_data, None
    elif isinstance(prompt_data, dict):
        # New format: object with template and optional entity_mapping
        template = prompt_data.get('template', '')
        mapping_data = prompt_data.get('entity_mapping')
        mapping = None
        if mapping_data:
            from models.schemas import EntityFieldMapping
            field_mappings = [
                EntityFieldMapping(**fm) for fm in mapping_data.get('field_mappings', [])
            ]
            mapping = EntityMapping(
                entity_type=mapping_data.get('entity_type', ''),
                fact_trigger=mapping_data.get('fact_trigger'),
                field_mappings=field_mappings
            )
        return template, mapping
    else:
        raise ValueError(f"Unexpected prompt data type: {type(prompt_data)}")


def _serialize_prompt_data(template: str, mapping: Optional[EntityMapping] = None) -> Union[str, dict]:
    """Serialize template and mapping to prompts.json format"""
    if mapping is None:
        # Use old format (string) for backward compatibility
        return template
    else:
        # Use new format (object)
        result = {'template': template}
        if mapping:
            result['entity_mapping'] = {
                'entity_type': mapping.entity_type,
                'fact_trigger': mapping.fact_trigger,
                'field_mappings': [
                    {
                        'template_placeholder': fm.template_placeholder,
                        'entity_type': fm.entity_type,
                        'field_name': fm.field_name,
                        **(dict(hardcoded_value=fm.hardcoded_value) if fm.hardcoded_value is not None else {}),
                        **(dict(value_code_mappings=fm.value_code_mappings) if fm.value_code_mappings else {})
                    }
                    for fm in mapping.field_mappings
                ]
            }
        return result


def save_prompts_json(data: Dict):
    """
    Save prompts back to the directory-based structure.

    For each center key in data, strips the -{center_lower} suffix from
    prompt keys and writes to {center}/prompts.json.
    """
    prompts_dir = get_latest_prompts_dir()
    prompts_dir.mkdir(parents=True, exist_ok=True)

    for center, center_prompts in data.items():
        center_lower = center.lower()
        suffix = f"-{center_lower}"

        # Strip the center suffix from keys before writing
        raw_prompts: Dict = {}
        for key, value in center_prompts.items():
            raw_key = key[: -len(suffix)] if key.endswith(suffix) else key
            raw_prompts[raw_key] = value

        center_dir = prompts_dir / center
        center_dir.mkdir(parents=True, exist_ok=True)
        prompts_file = center_dir / "prompts.json"
        with open(prompts_file, 'w', encoding='utf-8') as f:
            json.dump(raw_prompts, f, indent=2, ensure_ascii=False)


def _get_center_prompts(prompts_data: Dict, center: str) -> Dict:
    """Get prompt dict for a center; ensure center exists (create empty if missing for list)."""
    if center not in prompts_data:
        return {}
    return prompts_data[center]


# --- Centers (must be defined before /{prompt_type}) ---

@router.get("/centers", response_model=List[str])
async def list_centers():
    """List all center/group names (subdirectories in latest_prompts/)."""
    prompts_dir = get_latest_prompts_dir()
    if not prompts_dir.is_dir():
        return []
    return sorted(
        d.name for d in prompts_dir.iterdir()
        if d.is_dir() and (d / "prompts.json").exists()
    )


@router.post("/centers", response_model=dict)
async def create_center(body: CenterCreate):
    """Create a new center/group. Prompts can then be added to it."""
    center = body.center.strip()
    if not center:
        raise HTTPException(status_code=400, detail="Center name cannot be empty")

    prompts_dir = get_latest_prompts_dir()
    center_dir = prompts_dir / center
    if center_dir.is_dir() and (center_dir / "prompts.json").exists():
        raise HTTPException(status_code=400, detail=f"Center '{center}' already exists")

    center_dir.mkdir(parents=True, exist_ok=True)
    with open(center_dir / "prompts.json", 'w', encoding='utf-8') as f:
        json.dump({}, f, indent=2)
    return {"center": center, "message": f"Center '{center}' created"}


# --- Prompts (center-aware) ---

@router.get("", response_model=List[PromptInfo])
async def list_prompts(
    center: Optional[str] = Query(None, description="Filter by center; default INT")
):
    """List prompts for a center. If center omitted, defaults to INT."""
    c = center or DEFAULT_CENTER
    prompts_data = load_prompts_json()
    center_prompts = _get_center_prompts(prompts_data, c)
    result = []
    for prompt_type, prompt_data in center_prompts.items():
        template, mapping = _extract_template_and_mapping(prompt_data)
        result.append(PromptInfo(
            prompt_type=prompt_type,
            template=template,
            report_types=None,
            entity_mapping=mapping,
            center=c
        ))
    return result


@router.post("", response_model=PromptInfo)
async def create_prompt(create: PromptInfo):
    """Create a new prompt in a center. Default center is INT if not set."""
    prompts_data = load_prompts_json()
    c = (create.center or DEFAULT_CENTER).strip()
    if c not in prompts_data:
        prompts_data[c] = {}
    center_prompts = prompts_data[c]

    prompt_type = create.prompt_type.strip()
    if not prompt_type:
        raise HTTPException(
            status_code=400,
            detail="Prompt type name cannot be empty"
        )
    if prompt_type in center_prompts:
        raise HTTPException(
            status_code=400,
            detail=f"Prompt type '{prompt_type}' already exists in center '{c}'"
        )
    template = create.template.strip()
    if not template:
        raise HTTPException(
            status_code=400,
            detail="Prompt template cannot be empty"
        )
    center_prompts[prompt_type] = _serialize_prompt_data(template, create.entity_mapping)
    prompts_data[c] = center_prompts
    save_prompts_json(prompts_data)
    return PromptInfo(
        prompt_type=prompt_type,
        template=template,
        report_types=create.report_types,
        entity_mapping=create.entity_mapping,
        center=c
    )


@router.get("/{prompt_type}", response_model=PromptInfo)
async def get_prompt(
    prompt_type: str,
    center: Optional[str] = Query(None, description="Center; default INT")
):
    """Get a specific prompt by type and center."""
    c = center or DEFAULT_CENTER
    prompts_data = load_prompts_json()
    center_prompts = _get_center_prompts(prompts_data, c)
    if prompt_type not in center_prompts:
        raise HTTPException(
            status_code=404,
            detail=f"Prompt type '{prompt_type}' not found in center '{c}'. Available: {list(center_prompts.keys())}"
        )
    template, mapping = _extract_template_and_mapping(center_prompts[prompt_type])
    return PromptInfo(
        prompt_type=prompt_type,
        template=template,
        report_types=None,
        entity_mapping=mapping,
        center=c
    )


@router.put("/{prompt_type}", response_model=PromptInfo)
async def update_prompt(
    prompt_type: str,
    update: PromptUpdate,
    center: Optional[str] = Query(None, description="Center; default INT")
):
    """Update prompt template and/or entity mapping."""
    c = center or DEFAULT_CENTER
    prompts_data = load_prompts_json()
    center_prompts = _get_center_prompts(prompts_data, c)
    if prompt_type not in center_prompts:
        raise HTTPException(
            status_code=404,
            detail=f"Prompt type '{prompt_type}' not found in center '{c}'"
        )
    center_prompts[prompt_type] = _serialize_prompt_data(update.template, update.entity_mapping)
    prompts_data[c] = center_prompts
    save_prompts_json(prompts_data)
    return PromptInfo(
        prompt_type=prompt_type,
        template=update.template,
        report_types=None,
        entity_mapping=update.entity_mapping,
        center=c
    )


@router.post("/{prompt_type}/rename", response_model=PromptInfo)
async def rename_prompt(
    prompt_type: str,
    rename: PromptRename,
    center: Optional[str] = Query(None, description="Center; default INT")
):
    """Rename a prompt type within a center."""
    c = center or DEFAULT_CENTER
    prompts_data = load_prompts_json()
    center_prompts = _get_center_prompts(prompts_data, c)
    if prompt_type not in center_prompts:
        raise HTTPException(
            status_code=404,
            detail=f"Prompt type '{prompt_type}' not found in center '{c}'"
        )
    new_name = rename.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="New name cannot be empty")
    if new_name in center_prompts:
        raise HTTPException(
            status_code=400,
            detail=f"Prompt type '{new_name}' already exists in center '{c}'"
        )
    prompt_data = center_prompts.pop(prompt_type)
    center_prompts[new_name] = prompt_data
    prompts_data[c] = center_prompts
    save_prompts_json(prompts_data)
    template, mapping = _extract_template_and_mapping(prompt_data)
    return PromptInfo(
        prompt_type=new_name,
        template=template,
        report_types=None,
        entity_mapping=mapping,
        center=c
    )


@router.delete("/{prompt_type}", status_code=204)
async def delete_prompt(
    prompt_type: str,
    center: Optional[str] = Query(None, description="Center; default INT")
):
    """Delete a prompt from a center."""
    c = center or DEFAULT_CENTER
    prompts_data = load_prompts_json()
    center_prompts = _get_center_prompts(prompts_data, c)
    if prompt_type not in center_prompts:
        raise HTTPException(
            status_code=404,
            detail=f"Prompt type '{prompt_type}' not found in center '{c}'"
        )
    del center_prompts[prompt_type]
    prompts_data[c] = center_prompts
    save_prompts_json(prompts_data)
    return None

