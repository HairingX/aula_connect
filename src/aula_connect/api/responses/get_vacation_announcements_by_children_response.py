"""Aula's answer to presence.getVacationAnnouncementsByChildren, as far as it is read."""

from typing import List, NotRequired, TypedDict

from .common_data import AulaStatusData


class AulaPresenceChildData(TypedDict):
    """The child a group of the answer is about."""
    id: NotRequired[int|None]
    name: NotRequired[str|None]


class AulaVacationAnnouncementData(TypedDict):
    """A vacation or time off registered for the child."""
    description: NotRequired[str|None]
    endDate: NotRequired[str|None]
    isEditable: NotRequired[bool|None]
    startDate: NotRequired[str|None]
    vacationId: NotRequired[int|None]


class AulaChildVacationAnnouncementsData(TypedDict):
    """The vacations of one child."""
    child: NotRequired[AulaPresenceChildData|None]
    vacationAnnouncements: NotRequired[List[AulaVacationAnnouncementData]|None]


class AulaGetVacationAnnouncementsByChildrenResponse(TypedDict):
    """The answer, with each child's vacations."""
    data: List[AulaChildVacationAnnouncementsData]
    status: AulaStatusData
