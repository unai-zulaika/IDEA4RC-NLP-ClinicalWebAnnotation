"""
CRUD routes for Annotation Presets.
Storage: individual JSON files in backend/data/presets/{uuid}.json
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from models.schemas import AnnotationPreset, AnnotationPresetCreate, AnnotationPresetUpdate

router = APIRouter()


def _get_presets_dir() -> Path:
    d = Path(__file__).resolve().parent.parent / "data" / "presets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_preset(preset_id: str) -> dict:
    path = _get_presets_dir() / f"{preset_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Preset {preset_id} not found")
    return json.loads(path.read_text())


def _save_preset(preset_id: str, data: dict) -> None:
    path = _get_presets_dir() / f"{preset_id}.json"
    path.write_text(json.dumps(data, indent=2))


@router.get("", response_model=list[AnnotationPreset])
async def list_presets(center: Optional[str] = Query(None)):
    """List all presets, optionally filtered by center. Sorted by updated_at desc."""
    presets_dir = _get_presets_dir()
    presets = []
    for f in presets_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if center and data.get("center") != center:
                continue
            presets.append(data)
        except (json.JSONDecodeError, KeyError):
            continue
    presets.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
    return presets


@router.get("/{preset_id}", response_model=AnnotationPreset)
async def get_preset(preset_id: str):
    """Get a single preset by ID."""
    return _load_preset(preset_id)


@router.post("", response_model=AnnotationPreset, status_code=201)
async def create_preset(body: AnnotationPresetCreate):
    """Create a new preset."""
    now = datetime.now(timezone.utc).isoformat()
    preset_id = str(uuid.uuid4())
    data = {
        "id": preset_id,
        "name": body.name,
        "center": body.center,
        "description": body.description,
        "report_type_mapping": body.report_type_mapping,
        "created_at": now,
        "updated_at": now,
    }
    _save_preset(preset_id, data)
    return data


@router.put("/{preset_id}", response_model=AnnotationPreset)
async def update_preset(preset_id: str, body: AnnotationPresetUpdate):
    """Partial update of a preset. Only provided fields are updated."""
    data = _load_preset(preset_id)
    update_fields = body.model_dump(exclude_unset=True)
    for key, value in update_fields.items():
        data[key] = value
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_preset(preset_id, data)
    return data


@router.delete("/{preset_id}", status_code=200)
async def delete_preset(preset_id: str):
    """Delete a preset."""
    path = _get_presets_dir() / f"{preset_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Preset {preset_id} not found")
    path.unlink()
    return {"success": True, "message": f"Preset {preset_id} deleted"}
