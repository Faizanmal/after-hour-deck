from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Desk(Base):
    """One tester's private clinic board. Shared catalog, separate bookings."""

    __tablename__ = "desks"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    patients: Mapped[list[Patient]] = relationship(back_populates="desk")
    appointments: Mapped[list[Appointment]] = relationship(back_populates="desk")


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    short_code: Mapped[str] = mapped_column(String(32), unique=True)
    specialty: Mapped[str] = mapped_column(String(80))

    slots: Mapped[list[Slot]] = relationship(back_populates="provider")


class VisitType(Base):
    __tablename__ = "visit_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    duration_minutes: Mapped[int]
    prep_instructions: Mapped[str] = mapped_column(Text)

    appointments: Mapped[list[Appointment]] = relationship(back_populates="visit_type")
    slots: Mapped[list[Slot]] = relationship(back_populates="visit_type")


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    desk_id: Mapped[int] = mapped_column(ForeignKey("desks.id"))
    full_name: Mapped[str] = mapped_column(String(160))
    date_of_birth: Mapped[date] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(40), default="")

    desk: Mapped[Desk] = relationship(back_populates="patients")
    appointments: Mapped[list[Appointment]] = relationship(back_populates="patient")

    __table_args__ = (
        UniqueConstraint("desk_id", "full_name", "date_of_birth", name="uq_patient_name_dob"),
    )


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    visit_type_id: Mapped[int] = mapped_column(ForeignKey("visit_types.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)

    provider: Mapped[Provider] = relationship(back_populates="slots")
    visit_type: Mapped[VisitType] = relationship(back_populates="slots")
    appointments: Mapped[list[Appointment]] = relationship(back_populates="slot")


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40))
    desk_id: Mapped[int] = mapped_column(ForeignKey("desks.id"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"))
    visit_type_id: Mapped[int] = mapped_column(ForeignKey("visit_types.id"))
    status: Mapped[str] = mapped_column(String(20), default="booked")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    desk: Mapped[Desk] = relationship(back_populates="appointments")
    patient: Mapped[Patient] = relationship(back_populates="appointments")
    slot: Mapped[Slot] = relationship(back_populates="appointments")
    visit_type: Mapped[VisitType] = relationship(back_populates="appointments")

    __table_args__ = (
        UniqueConstraint("desk_id", "slot_id", name="uq_desk_slot"),
        UniqueConstraint("desk_id", "public_id", name="uq_desk_public_id"),
    )
