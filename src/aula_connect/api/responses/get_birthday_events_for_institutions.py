"""Aula's answer to calendar.getBirthdayEventsForInstitutions."""

from typing import List, NotRequired, TypedDict

from .common_data import AulaStatusData

class AulaBirthdayEventData(TypedDict):
    """A birthday."""
    institutionProfileId: int
    birthday: str
    institutionCode: str
    mainGroupName: NotRequired[str|None]
    name: str
    relatedChildrenIds: NotRequired[List[int]]

class AulaGetBirthdayEventsForInstitutionsResponse(TypedDict):
    """The answer, with the birthdays."""
    data: List[AulaBirthdayEventData]
    status: AulaStatusData
    version: int