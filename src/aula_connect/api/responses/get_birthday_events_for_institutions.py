"""Aula's answer to calendar.getBirthdayEventsForInstitutions."""

import datetime
from typing import List, TypedDict
from typing import List
from datetime import datetime

from .common_data import AulaStatusData

class AulaBirthdayEventData(TypedDict):
    """A birthday."""
    institutionProfileId: int
    birthday: datetime
    institutionCode: str
    name: str

class AulaGetBirthdayEventsForInstitutionsResponse(TypedDict):
    """The answer, with the birthdays."""
    data: List[AulaBirthdayEventData]
    status: AulaStatusData
    version: int