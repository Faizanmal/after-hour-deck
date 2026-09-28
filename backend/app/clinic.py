from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any

from dateutil import parser as date_parser
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models import Appointment, Desk, Patient, Provider, Slot, VisitType
from app.seed import clinic_zone


def _norm(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", folded.lower()).strip()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date_parser.parse(value, fuzzy=True).date()
    except (ValueError, OverflowError, TypeError):
        return None


def ensure_aware(dt: datetime) -> datetime:
    tz = clinic_zone()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _spoken_when(dt: datetime) -> str:
    local = ensure_aware(dt)
    hour = local.strftime("%I").lstrip("0")
    minute = local.strftime("%M")
    ampm = "in the morning" if local.hour < 12 else "in the afternoon" if local.hour < 17 else "in the evening"
    time_bit = hour if minute == "00" else f"{hour}:{minute}"
    return f"{local.strftime('%A, %B')} {local.day} at {time_bit} {ampm}"


def _slot_payload(slot: Slot) -> dict[str, Any]:
    return {
        "slot_id": slot.public_id,
        "when": _spoken_when(slot.start_at),
        "start_at": slot.start_at.isoformat(),
        "provider": slot.provider.name,
        "visit_type": slot.visit_type.slug,
        "duration_minutes": slot.visit_type.duration_minutes,
    }


def _appointment_payload(appt: Appointment) -> dict[str, Any]:
    return {
        "appointment_id": appt.public_id,
        "status": appt.status,
        "patient": appt.patient.full_name,
        "when": _spoken_when(appt.slot.start_at),
        "start_at": appt.slot.start_at.isoformat(),
        "provider": appt.slot.provider.name,
        "visit_type": appt.visit_type.slug,
        "phone": appt.patient.phone,
    }


def _for_update(db: Session, statement):
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        return statement.with_for_update()
    return statement


def _booked_slot_ids(desk_id: int):
    return select(Appointment.slot_id).where(
        Appointment.desk_id == desk_id,
        Appointment.status == "booked",
    )


def lookup_patient(db: Session, desk: Desk, name: str, date_of_birth: str) -> dict[str, Any]:
    dob = _parse_date(date_of_birth)
    if not dob:
        return {
            "error": (
                f"Could not read date of birth '{date_of_birth}'. "
                "Ask for year-month-day, for example April 12, 1988."
            )
        }

    patients = db.scalars(select(Patient).where(Patient.desk_id == desk.id)).all()
    needle = _norm(name)
    matches = [
        p
        for p in patients
        if p.date_of_birth == dob and (needle in _norm(p.full_name) or _norm(p.full_name) in needle)
    ]
    if not matches:
        return {
            "found": False,
            "message": (
                f"No patient named {name} with date of birth {dob.isoformat()} is on file. "
                "You can still book them as a new patient if you have a phone number."
            ),
        }
    patient = matches[0]
    appts = db.scalars(
        select(Appointment)
        .options(joinedload(Appointment.slot).joinedload(Slot.provider), joinedload(Appointment.visit_type), joinedload(Appointment.patient))
        .where(
            Appointment.desk_id == desk.id,
            Appointment.patient_id == patient.id,
            Appointment.status == "booked",
        )
        .order_by(Appointment.id.desc())
    ).all()
    return {
        "found": True,
        "patient": {
            "name": patient.full_name,
            "date_of_birth": patient.date_of_birth.isoformat(),
            "phone": patient.phone,
        },
        "upcoming": [_appointment_payload(a) for a in appts],
    }


def list_available_slots(
    db: Session,
    desk: Desk,
    visit_type: str,
    on_date: str | None = None,
    provider_name: str | None = None,
) -> dict[str, Any]:
    slug = _norm(visit_type).replace(" ", "")
    aliases = {
        "cleaning": "cleaning",
        "hygiene": "cleaning",
        "checkup": "cleaning",
        "consult": "consult",
        "consultation": "consult",
        "exam": "consult",
        "emergency": "emergency",
        "urgent": "emergency",
        "pain": "emergency",
    }
    slug = aliases.get(slug, slug)
    visit = db.scalar(select(VisitType).where(VisitType.slug == slug))
    if not visit:
        return {
            "error": (
                f"Visit type '{visit_type}' is not offered. "
                "Ask the caller to choose cleaning, consult, or emergency."
            )
        }

    tz = clinic_zone()
    now = datetime.now(tz)
    target = _parse_date(on_date)
    query = (
        select(Slot)
        .options(joinedload(Slot.provider), joinedload(Slot.visit_type))
        .where(
            Slot.visit_type_id == visit.id,
            Slot.start_at > now,
            Slot.id.not_in(_booked_slot_ids(desk.id)),
        )
        .order_by(Slot.start_at.asc())
    )
    if target:
        start = datetime.combine(target, datetime.min.time(), tzinfo=tz)
        end = start + timedelta(days=1)
        query = query.where(Slot.start_at >= start, Slot.start_at < end)

    slots = db.scalars(query).all()
    if provider_name:
        pneedle = _norm(provider_name)
        slots = [s for s in slots if pneedle in _norm(s.provider.name) or pneedle in _norm(s.provider.short_code)]

    slots = slots[:6]
    if not slots:
        return {
            "count": 0,
            "visit_type": visit.slug,
            "message": "No open slots match that request. Offer another day or visit type.",
            "slots": [],
        }
    return {"count": len(slots), "visit_type": visit.slug, "slots": [_slot_payload(s) for s in slots]}


def _find_or_create_patient(db: Session, desk: Desk, name: str, dob: date, phone: str) -> Patient:
    patients = db.scalars(select(Patient).where(Patient.desk_id == desk.id)).all()
    needle = _norm(name)
    cleaned = name.strip()
    for patient in patients:
        if patient.date_of_birth == dob and needle in _norm(patient.full_name):
            if phone and not patient.phone:
                patient.phone = phone
            return patient
    patient = Patient(desk_id=desk.id, full_name=cleaned, date_of_birth=dob, phone=phone)
    try:
        with db.begin_nested():
            db.add(patient)
            db.flush()
    except IntegrityError:
        found = db.scalar(
            select(Patient).where(
                Patient.desk_id == desk.id,
                Patient.full_name == cleaned,
                Patient.date_of_birth == dob,
            )
        )
        if found is None:
            raise
        if phone and not found.phone:
            found.phone = phone
        return found
    return patient


def _reserve_slot(
    db: Session,
    desk: Desk,
    slot: Slot,
    patient_name: str,
    dob: date,
    phone: str,
) -> int | None:
    prior = db.scalar(
        _for_update(
            db,
            select(Appointment).where(
                Appointment.desk_id == desk.id,
                Appointment.slot_id == slot.id,
            ),
        )
    )
    if prior is not None and prior.status == "booked":
        return None
    patient = _find_or_create_patient(db, desk, patient_name, dob, phone)
    now = datetime.now(clinic_zone())
    if prior is not None:
        prior.status = "booked"
        prior.patient_id = patient.id
        prior.visit_type_id = slot.visit_type_id
        prior.notes = ""
        prior.created_at = now
        db.flush()
        return prior.id
    appt = Appointment(
        public_id=f"APT-{slot.public_id}",
        desk_id=desk.id,
        patient_id=patient.id,
        slot_id=slot.id,
        visit_type_id=slot.visit_type_id,
        status="booked",
        notes="",
        created_at=now,
    )
    db.add(appt)
    db.flush()
    return appt.id


def book_appointment(
    db: Session,
    desk: Desk,
    slot_id: str,
    patient_name: str,
    date_of_birth: str,
    phone: str,
    visit_type: str,
    caller_confirmed: bool,
) -> dict[str, Any]:
    if not caller_confirmed:
        return {
            "error": (
                "Booking refused: caller_confirmed is false. "
                "Read the name, date, and time back, get an explicit yes, then call again."
            )
        }

    dob = _parse_date(date_of_birth)
    if not dob:
        return {"error": f"Could not read date of birth '{date_of_birth}'. Ask again as month, day, year."}

    slot = db.scalar(
        select(Slot)
        .options(joinedload(Slot.provider), joinedload(Slot.visit_type))
        .where(Slot.public_id == slot_id.strip())
    )
    if not slot:
        return {
            "error": (
                f"Slot '{slot_id}' does not exist. Call list_available_slots and use a slot_id from that result."
            )
        }
    wanted = _norm(visit_type).replace(" ", "")
    if wanted and wanted not in {slot.visit_type.slug, _norm(slot.visit_type.name).replace(" ", "")}:
        return {
            "error": (
                f"Slot {slot_id} is a {slot.visit_type.slug} visit, not '{visit_type}'. "
                "Pick a matching slot or change the visit type."
            )
        }

    taken = f"Slot {slot_id} is no longer open. Offer a different slot from list_available_slots."
    try:
        with db.begin_nested():
            appt_id = _reserve_slot(db, desk, slot, patient_name, dob, phone.strip())
    except IntegrityError:
        return {"error": taken}
    if appt_id is None:
        return {"error": taken}

    appt = db.scalar(
        select(Appointment)
        .options(
            joinedload(Appointment.patient),
            joinedload(Appointment.visit_type),
            joinedload(Appointment.slot).joinedload(Slot.provider),
        )
        .where(Appointment.id == appt_id)
    )
    assert appt is not None
    return {"booked": True, "appointment": _appointment_payload(appt)}


def cancel_appointment(
    db: Session,
    desk: Desk,
    appointment_id: str | None = None,
    patient_name: str | None = None,
    on_date: str | None = None,
) -> dict[str, Any]:
    appt: Appointment | None = None
    if appointment_id:
        appt = db.scalar(
            select(Appointment)
            .options(
                joinedload(Appointment.patient),
                joinedload(Appointment.visit_type),
                joinedload(Appointment.slot).joinedload(Slot.provider),
            )
            .where(
                Appointment.desk_id == desk.id,
                Appointment.public_id == appointment_id.strip(),
            )
        )
    elif patient_name:
        patients = db.scalars(select(Patient).where(Patient.desk_id == desk.id)).all()
        needle = _norm(patient_name)
        matched = [p for p in patients if needle in _norm(p.full_name) or _norm(p.full_name) in needle]
        if not matched:
            return {"error": f"No patient matching '{patient_name}' has a booking."}
        query = (
            select(Appointment)
            .options(
                joinedload(Appointment.patient),
                joinedload(Appointment.visit_type),
                joinedload(Appointment.slot).joinedload(Slot.provider),
            )
            .where(
                Appointment.desk_id == desk.id,
                Appointment.patient_id == matched[0].id,
                Appointment.status == "booked",
            )
            .order_by(Appointment.id.desc())
        )
        target = _parse_date(on_date)
        appts = db.scalars(query).all()
        if target:
            appts = [a for a in appts if ensure_aware(a.slot.start_at).date() == target]
        if not appts:
            return {"error": f"No booked visit found for {matched[0].full_name}."}
        if len(appts) > 1 and not target:
            return {
                "error": (
                    f"{matched[0].full_name} has more than one visit. "
                    "Ask which date to cancel, then call again with on_date."
                ),
                "upcoming": [_appointment_payload(a) for a in appts],
            }
        appt = appts[0]

    if appt is None:
        return {"error": "Need appointment_id, or patient_name (and date if they have more than one visit)."}
    if appt.status == "cancelled":
        return {"error": f"{appt.public_id} is already cancelled."}

    appt.status = "cancelled"
    db.flush()
    return {"cancelled": True, "appointment": _appointment_payload(appt)}


def get_prep_instructions(db: Session, visit_type: str) -> dict[str, Any]:
    slug = _norm(visit_type).replace(" ", "")
    aliases = {"cleaning": "cleaning", "hygiene": "cleaning", "consult": "consult", "consultation": "consult", "emergency": "emergency"}
    slug = aliases.get(slug, slug)
    visit = db.scalar(select(VisitType).where(VisitType.slug == slug))
    if not visit:
        return {"error": "Visit type not found. Use cleaning, consult, or emergency."}
    return {
        "visit_type": visit.slug,
        "name": visit.name,
        "duration_minutes": visit.duration_minutes,
        "instructions": visit.prep_instructions,
    }


def list_board(db: Session, desk: Desk) -> dict[str, Any]:
    tz = clinic_zone()
    now = datetime.now(tz)
    horizon = now + timedelta(days=14)
    appts = (
        db.scalars(
            select(Appointment)
            .join(Slot, Appointment.slot_id == Slot.id)
            .options(
                joinedload(Appointment.patient),
                joinedload(Appointment.visit_type),
                joinedload(Appointment.slot).joinedload(Slot.provider),
            )
            .where(
                Appointment.desk_id == desk.id,
                Slot.start_at >= now - timedelta(hours=2),
            )
            .order_by(Slot.start_at.asc())
        )
        .unique()
        .all()
    )
    open_count = db.scalar(
        select(func.count())
        .select_from(Slot)
        .where(
            Slot.start_at.between(now, horizon),
            Slot.id.not_in(_booked_slot_ids(desk.id)),
        )
    )
    providers = db.scalars(select(Provider).order_by(Provider.id)).all()
    visit_types = db.scalars(select(VisitType).order_by(VisitType.id)).all()
    return {
        "open_slots": int(open_count or 0),
        "timezone": str(tz),
        "providers": [{"name": p.name, "specialty": p.specialty} for p in providers],
        "visit_types": [
            {"slug": v.slug, "name": v.name, "duration_minutes": v.duration_minutes} for v in visit_types
        ],
        "appointments": [_appointment_payload(a) for a in appts],
    }
