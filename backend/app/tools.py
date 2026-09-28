from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app import clinic
from app.models import Desk

ToolHandler = Callable[..., dict[str, Any]]


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "lookup_patient",
        "description": (
            "Look up a patient already on file. Call this when the caller gives a name and date of birth. "
            "Returns upcoming visits if they have any."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Patient full name as spoken, e.g. Maya Hernandez.",
                    "examples": ["Maya Hernandez", "James Okonkwo", "Priya Shah"],
                },
                "date_of_birth": {
                    "type": "string",
                    "description": "Date of birth as an ISO date (YYYY-MM-DD).",
                    "format": "date",
                    "examples": ["1988-04-12", "1975-11-03", "1992-07-21"],
                },
            },
            "required": ["name", "date_of_birth"],
        },
        "execution_mode": "interactive",
        "timeout_seconds": 30,
    },
    {
        "type": "function",
        "name": "list_available_slots",
        "description": (
            "List open appointment slots. Always call this before offering times. "
            "Do not invent times. Read back at most three options."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "visit_type": {
                    "type": "string",
                    "description": "Kind of visit.",
                    "enum": ["cleaning", "consult", "emergency"],
                },
                "on_date": {
                    "type": "string",
                    "description": "Preferred calendar day as YYYY-MM-DD. Omit to search the next two weeks.",
                    "format": "date",
                    "examples": ["2026-09-17", "2026-09-18"],
                },
                "provider_name": {
                    "type": "string",
                    "description": "Optional provider last name, e.g. Patel or Chen.",
                    "examples": ["Patel", "Chen"],
                },
            },
            "required": ["visit_type"],
        },
        "execution_mode": "interactive",
        "timeout_seconds": 30,
    },
    {
        "type": "function",
        "name": "book_appointment",
        "description": (
            "Book a slot. Only call after the caller has confirmed name, date, and time out loud. "
            "Pass caller_confirmed true only after that explicit yes. slot_id must come from list_available_slots."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "slot_id": {
                    "type": "string",
                    "description": "The slot_id string returned by list_available_slots, e.g. 0917-1430-PATEL.",
                    "examples": ["0917-1430-PATEL", "0918-0900-CHEN"],
                },
                "patient_name": {
                    "type": "string",
                    "description": "Full name to put on the visit.",
                    "examples": ["Maya Hernandez"],
                },
                "date_of_birth": {
                    "type": "string",
                    "description": "Patient date of birth as YYYY-MM-DD.",
                    "format": "date",
                    "examples": ["1988-04-12"],
                },
                "phone": {
                    "type": "string",
                    "description": "Callback number in any common US form.",
                    "examples": ["+1-555-0101", "5550101"],
                },
                "visit_type": {
                    "type": "string",
                    "enum": ["cleaning", "consult", "emergency"],
                },
                "caller_confirmed": {
                    "type": "boolean",
                    "description": "True only if the caller just confirmed name, date, and time.",
                },
            },
            "required": [
                "slot_id",
                "patient_name",
                "date_of_birth",
                "phone",
                "visit_type",
                "caller_confirmed",
            ],
        },
        "execution_mode": "hold",
        "timeout_seconds": 30,
    },
    {
        "type": "function",
        "name": "cancel_appointment",
        "description": (
            "Cancel a booked visit and free the slot. Prefer appointment_id when you have it. "
            "Otherwise use patient_name and on_date."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "appointment_id": {
                    "type": "string",
                    "description": "Public appointment id, e.g. APT-MAYA-001.",
                    "examples": ["APT-MAYA-001"],
                },
                "patient_name": {
                    "type": "string",
                    "description": "Patient full name if you do not have appointment_id.",
                },
                "on_date": {
                    "type": "string",
                    "description": "Visit day as YYYY-MM-DD when the patient has more than one booking.",
                    "format": "date",
                },
            },
        },
        "execution_mode": "hold",
        "timeout_seconds": 30,
    },
    {
        "type": "function",
        "name": "get_prep_instructions",
        "description": "Get spoken prep instructions for a visit type. Use for 'what should I do before my cleaning?'",
        "parameters": {
            "type": "object",
            "properties": {
                "visit_type": {
                    "type": "string",
                    "enum": ["cleaning", "consult", "emergency"],
                }
            },
            "required": ["visit_type"],
        },
        "execution_mode": "interactive",
        "timeout_seconds": 15,
    },
]


def run_tool(db: Session, desk: Desk, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handlers: dict[str, ToolHandler] = {
        "lookup_patient": lambda: clinic.lookup_patient(
            db, desk, arguments.get("name", ""), arguments.get("date_of_birth", "")
        ),
        "list_available_slots": lambda: clinic.list_available_slots(
            db,
            desk,
            arguments.get("visit_type", ""),
            arguments.get("on_date"),
            arguments.get("provider_name"),
        ),
        "book_appointment": lambda: clinic.book_appointment(
            db,
            desk,
            arguments.get("slot_id", ""),
            arguments.get("patient_name", ""),
            arguments.get("date_of_birth", ""),
            arguments.get("phone", ""),
            arguments.get("visit_type", ""),
            bool(arguments.get("caller_confirmed")),
        ),
        "cancel_appointment": lambda: clinic.cancel_appointment(
            db,
            desk,
            arguments.get("appointment_id"),
            arguments.get("patient_name"),
            arguments.get("on_date"),
        ),
        "get_prep_instructions": lambda: clinic.get_prep_instructions(
            db, arguments.get("visit_type", "")
        ),
    }
    handler = handlers.get(name)
    if handler is None:
        return {"error": f"Unknown tool '{name}'. Do not invent tools."}
    try:
        return handler()
    except Exception as exc:  # noqa: BLE001 — return a model-readable error
        return {"error": f"{name} failed: {exc}. Apologize and offer to try again."}
