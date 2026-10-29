"""EasyIQ's answer to weekplaninfo."""

from typing import List, TypedDict


class AulaEasyiqWeekplanEvent(TypedDict):
    """An event of a weekly plan."""
    start: str
    end: str
    itemType: str
    title: str
    ownername: str
    description: str


class AulaGetEasyiqWeekplanResponse(TypedDict):
    """The answer, with the events of the week."""
    Events: List[AulaEasyiqWeekplanEvent]
