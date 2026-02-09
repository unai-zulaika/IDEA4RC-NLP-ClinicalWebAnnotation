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


def get_prompts_json_path() -> Path:
    """Get path to prompts.json"""
    # From routes/prompts.py: routes -> backend
    backend_dir = Path(__file__).parent.parent
    return backend_dir / "data" / "prompts" / "prompts.json"


def load_prompts_json() -> Dict:
    """Load prompts.json file"""
    prompts_path = get_prompts_json_path()
    if not prompts_path.exists():
        raise HTTPException(status_code=404, detail=f"Prompts file not found: {prompts_path}")
    
    with open(prompts_path, 'r', encoding='utf-8') as f:
        return json.load(f)


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
    """Save prompts.json file"""
    prompts_path = get_prompts_json_path()
    with open(prompts_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _get_center_prompts(prompts_data: Dict, center: str) -> Dict:
    """Get prompt dict for a center; ensure center exists (create empty if missing for list)."""
    if center not in prompts_data:
        return {}
    return prompts_data[center]


# --- Centers (must be defined before /{prompt_type}) ---

@router.get("/centers", response_model=List[str])
async def list_centers():
    """List all center/group names (top-level keys in prompts.json)."""
    prompts_data = load_prompts_json()
    return list(prompts_data.keys())


@router.post("/centers", response_model=dict)
async def create_center(body: CenterCreate):
    """Create a new center/group. Prompts can then be added to it."""
    prompts_data = load_prompts_json()
    center = body.center.strip()
    if not center:
        raise HTTPException(status_code=400, detail="Center name cannot be empty")
    if center in prompts_data:
        raise HTTPException(status_code=400, detail=f"Center '{center}' already exists")
    prompts_data[center] = {}
    save_prompts_json(prompts_data)
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

