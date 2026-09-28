from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Appointment, Desk, Patient, Provider, Slot, VisitType

DEMO_PATIENTS = [
    ("Maya Hernandez", "1988-04-12", "+1-555-0101"),
    ("James Okonkwo", "1975-11-03", "+1-555-0102"),
    ("Priya Shah", "1992-07-21", "+1-555-0103"),
]

PROVIDERS = [
    ("Dr. Amina Patel", "PATEL", "Hygiene"),
    ("Dr. Wei Chen", "CHEN", "General dentistry"),
]

VISIT_TYPES = [
    (
        "cleaning",
        "Cleaning",
        45,
        (
            "Please arrive ten minutes early and bring your insurance card. "
            "If fluoride is applied, avoid eating or drinking for thirty minutes after."
        ),
    ),
    (
        "consult",
        "Consult",
        30,
        (
            "Bring a list of current medications and any recent dental x-rays. "
            "No fasting is required."
        ),
    ),
    (
        "emergency",
        "Emergency",
        20,
        (
            "If there is swelling, fever, or trouble breathing, go to an emergency room. "
            "Otherwise come straight in. Ice packs can help with swelling on the way."
        ),
    ),
]


def clinic_zone() -> ZoneInfo:
    return ZoneInfo(get_settings().clinic_tz)


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(Provider.id).limit(1)):
        return

    providers = [
        Provider(name=name, short_code=code, specialty=specialty)
        for name, code, specialty in PROVIDERS
    ]
    db.add_all(providers)
    db.flush()

    visit_types = [
        VisitType(slug=slug, name=name, duration_minutes=mins, prep_instructions=prep)
        for slug, name, mins, prep in VISIT_TYPES
    ]
    db.add_all(visit_types)
    db.flush()

    tz = clinic_zone()
    today = datetime.now(tz).date()
    visit_by_slug = {vt.slug: vt for vt in visit_types}

    hours = [9, 10, 11, 13, 14, 15, 16]
    created = 0
    for day_offset in range(14):
        day = today + timedelta(days=day_offset)
        if day.weekday() >= 5:
            continue
        for provider in providers:
            for hour in hours:
                start = datetime.combine(day, time(hour, 0), tzinfo=tz)
                if start < datetime.now(tz):
                    continue
                visit = visit_by_slug["cleaning" if hour in (9, 10, 14) else "consult"]
                if hour == 16:
                    visit = visit_by_slug["emergency"]
                end = start + timedelta(minutes=visit.duration_minutes)
                public_id = f"{start.strftime('%m%d')}-{start.strftime('%H%M')}-{provider.short_code}"
                db.add(
                    Slot(
                        public_id=public_id,
                        provider_id=provider.id,
                        visit_type_id=visit.id,
                        start_at=start,
                        end_at=end,
                        is_open=True,
                    )
                )
                created += 1

    db.flush()
    _ = created


def seed_desk(db: Session, desk: Desk) -> None:
    """Copy the demo patients and Maya's visit onto one tester's board."""
    for full_name, dob, phone in DEMO_PATIENTS:
        db.add(
            Patient(
                desk_id=desk.id,
                full_name=full_name,
                date_of_birth=date.fromisoformat(dob),
                phone=phone,
            )
        )
    db.flush()

    tz = clinic_zone()
    now = datetime.now(tz)
    maya = db.scalar(
        select(Patient).where(Patient.desk_id == desk.id, Patient.full_name == "Maya Hernandez")
    )
    slot = db.scalar(select(Slot).where(Slot.start_at > now).order_by(Slot.start_at.asc()))
    if maya and slot:
        db.add(
            Appointment(
                public_id="APT-MAYA-001",
                desk_id=desk.id,
                patient_id=maya.id,
                slot_id=slot.id,
                visit_type_id=slot.visit_type_id,
                status="booked",
                notes="Seeded demo booking",
                created_at=now,
            )
        )
    db.flush()


def ensure_desk(db: Session, public_id: str) -> Desk:
    existing = db.scalar(select(Desk).where(Desk.public_id == public_id))
    if existing:
        return existing
    try:
        with db.begin_nested():
            desk = Desk(public_id=public_id, created_at=datetime.now(clinic_zone()))
            db.add(desk)
            db.flush()
            seed_desk(db, desk)
    except IntegrityError:
        existing = db.scalar(select(Desk).where(Desk.public_id == public_id))
        if existing is None:
            raise
        return existing
    return desk
