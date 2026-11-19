"""A child's vacations a guardian registered, and the institution's requests to say whether a child comes."""

from dataclasses import dataclass
from datetime import date, time
from typing import List


@dataclass
class AulaVacation:
    """A vacation or time off a guardian registered for a child ("Ferie/fri"), whole days."""
    id: int
    """The id of the calendar event Aula keeps it as."""
    child_id: int
    """The child's institution profile id."""
    start_date: date
    end_date: date
    """The last day."""
    description: str | None
    is_editable: bool


@dataclass
class AulaVacationRequest:
    """A request from the institution to say whether a child comes on the days of a period ("Ferieanmodning")."""
    id: int | None
    response_id: int
    """The id the request is read and answered by."""
    child_id: int
    """The child's institution profile id."""
    title: str
    start_date: date
    end_date: date
    response_deadline: date | None
    """The last day it can be answered; None where it has none."""
    note_to_guardian: str | None
    missing_answer: bool
    """Whether it has not been answered yet."""
    is_editable: bool
    is_presence_times_required: bool | None

    def answerable(self, today: date) -> bool:
        """Whether it can be answered on `today`: editable, and its deadline not past."""
        return self.is_editable and (self.response_deadline is None or self.response_deadline >= today)


@dataclass
class AulaVacationDay:
    """Whether a child comes on one day of a vacation request, and its times where they are asked for."""
    day: date
    is_coming: bool | None
    """None where the day has not been answered."""
    entry_time: time | None = None
    exit_time: time | None = None


@dataclass
class AulaVacationRequestDetail:
    """A vacation request, with its answer as it stands."""
    response_id: int
    child_id: int
    """The child's institution profile id."""
    start_date: date
    end_date: date
    response_deadline: date | None
    is_presence_times_required: bool
    """Whether a day the child comes is answered with its entry and exit times."""
    missing_answer: bool
    comment: str | None
    days: List[AulaVacationDay]
    """The days as answered, as Aula lists them."""
