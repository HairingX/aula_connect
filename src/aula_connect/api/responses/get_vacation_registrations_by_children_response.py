"""Aula's answer to presence.getVacationRegistrationsByChildren, as far as it is read."""

from typing import List, NotRequired, TypedDict

from .common_data import AulaStatusData
from .get_vacation_announcements_by_children_response import AulaPresenceChildData


class AulaVacationRegistrationData(TypedDict):
    """A request from the institution to say whether the child comes in a period."""
    endDate: NotRequired[str|None]
    isEditable: NotRequired[bool|None]
    isMissingAnswer: NotRequired[bool|None]
    isPresenceTimesRequired: NotRequired[bool|None]
    noteToGuardian: NotRequired[str|None]
    responseDeadline: NotRequired[str|None]
    responseId: NotRequired[int|None]
    startDate: NotRequired[str|None]
    title: NotRequired[str|None]
    vacationRegistrationId: NotRequired[int|None]


class AulaChildVacationRegistrationsData(TypedDict):
    """The requests about one child."""
    child: NotRequired[AulaPresenceChildData|None]
    vacationRegistrations: NotRequired[List[AulaVacationRegistrationData]|None]


class AulaGetVacationRegistrationsByChildrenResponse(TypedDict):
    """The answer, with the requests about each child."""
    data: List[AulaChildVacationRegistrationsData]
    status: AulaStatusData
