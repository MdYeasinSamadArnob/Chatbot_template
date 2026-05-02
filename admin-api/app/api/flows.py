"""
Flows REST API — CRUD for guided conversational flow definitions.

GET  /api/flows          → list all flows (hardcoded Python defaults merged with DB overrides)
GET  /api/flows/{key}    → single flow details including step definitions
PUT  /api/flows/{key}    → upsert DB override (requires x-admin-secret header)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.db.connection import AsyncSessionLocal
from app.db.repositories import (
    get_all_flow_definitions,
    get_flow_definition,
    upsert_flow_definition,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/flows", tags=["flows"])


# ── Auth helper ────────────────────────────────────────────────────────────

def _require_admin(secret: str) -> None:
    if settings.admin_secret and secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden — x-admin-secret required")


# ── Hardcoded Python flow defaults (imported at request time) ──────────────

def _get_python_flows() -> dict[str, dict[str, Any]]:
    """
    Return the hardcoded Python flow registry as serialisable dicts.
    Imported lazily so admin-api doesn't depend on bot-socket at startup.
    The admin-api doesn't have flow_definitions.py, so we reconstruct the
    schema from the FLOWS registry structure.
    """
    try:
        # Attempt to import from bot-socket if running in a shared venv
        from app.agent.flow_definitions import FLOWS  # type: ignore
        result: dict[str, dict[str, Any]] = {}
        for key, flow in FLOWS.items():
            result[key] = {
                "flow_key": key,
                "intent": flow.intent,
                "intro_text": flow.intro_text,
                "abort_confirmation": flow.abort_confirmation,
                "completion_text_template": flow.completion_text_template,
                "steps": [
                    {
                        "slot": s.slot,
                        "prompt_text": s.prompt_text,
                        "quick_replies": s.quick_replies,
                        "optional": s.optional,
                    }
                    for s in flow.steps
                ],
            }
        return result
    except ImportError:
        # admin-api running standalone — return empty; DB rows are the source
        return {}


def _merge_flow(python_default: dict[str, Any] | None, db_row: Any) -> dict[str, Any]:
    """Merge DB override row onto Python default dict."""
    base: dict[str, Any] = dict(python_default) if python_default else {}
    base.setdefault("flow_key", db_row.flow_key)
    base.setdefault("intent", None)
    base.setdefault("steps", [])

    if db_row.intent is not None:
        base["intent"] = db_row.intent
    if db_row.is_active is not None:
        base["is_active"] = db_row.is_active
    if db_row.intro_text is not None:
        base["intro_text"] = db_row.intro_text
    if db_row.abort_confirmation is not None:
        base["abort_confirmation"] = db_row.abort_confirmation
    if db_row.completion_text_template is not None:
        base["completion_text_template"] = db_row.completion_text_template
    if db_row.steps_json is not None:
        # Merge step-level overrides into base steps list
        step_map = {s["slot"]: s for s in base.get("steps", [])}
        for override in db_row.steps_json:
            slot = override.get("slot")
            if slot and slot in step_map:
                if override.get("prompt_text") is not None:
                    step_map[slot]["prompt_text"] = override["prompt_text"]
                if override.get("quick_replies") is not None:
                    step_map[slot]["quick_replies"] = override["quick_replies"]
        base["steps"] = list(step_map.values())

    base["_source"] = "db_override"
    base["updated_at"] = str(db_row.updated_at) if db_row.updated_at else None
    return base


# ── Request / Response schemas ─────────────────────────────────────────────

class QuickReply(BaseModel):
    label: str
    value: str


class StepOverride(BaseModel):
    slot: str
    prompt_text: str | None = None
    quick_replies: list[QuickReply] | None = None


class FlowUpsertRequest(BaseModel):
    is_active: bool | None = None
    intent: str | None = None
    intro_text: str | None = None
    abort_confirmation: str | None = None
    completion_text_template: str | None = None
    steps: list[StepOverride] | None = None


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("")
async def list_flows() -> list[dict[str, Any]]:
    """Return all known flows, merging Python defaults with DB overrides."""
    python_flows = _get_python_flows()
    async with AsyncSessionLocal() as session:
        db_rows = await get_all_flow_definitions(session)

    db_map = {row.flow_key: row for row in db_rows}

    # Start with all Python-defined flows
    result: list[dict[str, Any]] = []
    for key, pflow in python_flows.items():
        if key in db_map:
            result.append(_merge_flow(pflow, db_map[key]))
        else:
            merged = dict(pflow)
            merged["_source"] = "python_default"
            merged["updated_at"] = None
            result.append(merged)

    # Add any DB-only flows (not defined in Python)
    for key, row in db_map.items():
        if key not in python_flows:
            result.append(_merge_flow(None, row))

    return result


@router.get("/{flow_key}")
async def get_flow(flow_key: str) -> dict[str, Any]:
    python_flows = _get_python_flows()
    async with AsyncSessionLocal() as session:
        db_row = await get_flow_definition(session, flow_key)

    pflow = python_flows.get(flow_key)
    if pflow is None and db_row is None:
        raise HTTPException(status_code=404, detail=f"Flow '{flow_key}' not found")

    if db_row:
        return _merge_flow(pflow, db_row)

    merged = dict(pflow)  # type: ignore[arg-type]
    merged["_source"] = "python_default"
    merged["updated_at"] = None
    return merged


@router.put("/{flow_key}")
async def upsert_flow(
    flow_key: str,
    body: FlowUpsertRequest,
    x_admin_secret: str = Header(default=""),
) -> dict[str, Any]:
    """Create or update a flow definition DB override. Requires x-admin-secret."""
    _require_admin(x_admin_secret)

    # Build update dict — include every field the client sent; nulls clear DB overrides
    data: dict[str, Any] = {
        "is_active": body.is_active,
        "intent": body.intent,
        "intro_text": body.intro_text,
        "abort_confirmation": body.abort_confirmation,
        "completion_text_template": body.completion_text_template,
        "steps_json": (
            [s.model_dump(exclude_none=True) for s in body.steps]
            if body.steps is not None
            else None
        ),
    }
    # Drop keys the client explicitly left absent (still None after model default)
    data = {k: v for k, v in data.items() if v is not None or k in body.model_fields_set}

    async with AsyncSessionLocal() as session:
        row = await upsert_flow_definition(session, flow_key, data)

    python_flows = _get_python_flows()
    return _merge_flow(python_flows.get(flow_key), row)
