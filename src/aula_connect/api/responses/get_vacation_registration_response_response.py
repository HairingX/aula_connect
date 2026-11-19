"""Aula's answer to presence.getVacationRegistrationResponse, as far as it is read."""

from typing import List, NotRequired, TypedDict

from .common_data import AulaStatusData


class AulaVacationRegistrationDayData(TypedDict):
    """The answer for one day."""
    date: NotRequired[str|None]
    entryTime: NotRequired[str|None]
    exitTime: NotRequired[str|None]
    isComing: NotRequired[bool|None]


class AulaVacationRegistrationAnswerData(TypedDict):
    """The guardian's answer to a request, as it stands."""
    childId: NotRequired[int|None]
    comment: NotRequired[str|None]
    days: NotRequired[List[AulaVacationRegistrationDayData]|None]
    vacationRegistrationResponseId: NotRequired[int|None]


class AulaVacationRegistrationPeriodData(TypedDict):
    """The request: its period, its deadline and what an answer must hold."""
    endDate: NotRequired[str|None]
    isMissingAnswer: NotRequired[bool|None]
    isPresenceTimesRequired: NotRequired[bool|None]
    responseDeadline: NotRequired[str|None]
    startDate: NotRequired[str|None]


class AulaVacationRegistrationResponseData(TypedDict):
    """A request with its answer."""
    vacationRegistration: NotRequired[AulaVacationRegistrationPeriodData|None]
    vacationRegistrationResponse: NotRequired[AulaVacationRegistrationAnswerData|None]


class AulaGetVacationRegistrationResponseResponse(TypedDict):
    """The answer, with the request and its answer."""
    data: AulaVacationRegistrationResponseData
    status: AulaStatusData
