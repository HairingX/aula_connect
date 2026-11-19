"""A calendar event as Aula tells it alone: its description, organisers, invitations and answers."""

from dataclasses import dataclass
from datetime import datetime
from typing import List

from .aula_calendar_models import AulaCalendarEventTimeSlotEntryIndex


@dataclass
class AulaEventInvitation:
    """One invitation to an event and its answer, by the institution profile invited, not by name."""
    institution_profile_id: int
    response: str
    """Aula's answer, such as "accepted" or "waiting"."""
    answered_at: datetime | None


@dataclass
class AulaEventBooking:
    """A time booked in an event's time slots, by whom and for whom."""
    concerning_profile_id: int
    """The institution profile of the child the time is for."""
    institution_profile_id: int
    """The institution profile of whoever booked it."""
    time: AulaCalendarEventTimeSlotEntryIndex
    location: str | None


@dataclass
class AulaEventDetail:
    """A calendar event as Aula tells it alone.

    The invitations are kept without the names of those invited, and the bookings without the
    names of those they are for.
    """
    id: int
    title: str
    type: str
    all_day: bool
    start_datetime: datetime
    end_datetime: datetime
    description_html: str
    institution_name: str
    location: str | None
    creator_name: str
    creator_role: str
    """The creator's role at the institution, such as "teacher"."""
    co_organizer_names: List[str]
    invited_group_names: List[str]
    invitations: List[AulaEventInvitation]
    response_required: bool
    response_deadline: datetime | None
    deadline_exceeded: bool
    attachment_count: int
    private: bool
    deleted: bool
    bookings: List[AulaEventBooking]

    def invitation_of(self, institution_profile_ids: List[int]) -> AulaEventInvitation | None:
        """The invitation of one of the institution profiles; None where none is invited."""
        return next((invitation for invitation in self.invitations if invitation.institution_profile_id in institution_profile_ids), None)

    def booking_for(self, child_institution_profile_id: int) -> AulaEventBooking | None:
        """The time booked for the child; None where none is."""
        return next((booking for booking in self.bookings if booking.concerning_profile_id == child_institution_profile_id), None)
