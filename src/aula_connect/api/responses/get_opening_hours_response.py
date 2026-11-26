"""Aula's answers to presence.getClosedDays and presence.getOpeningHoursByInstitutionCodes, as far as they are read.

Their shapes are as Aula's own web app reads them.
"""

from typing import List, NotRequired, TypedDict

from .common_data import AulaStatusData


class AulaClosedDayData(TypedDict):
    """Days an institution is closed, such as a holiday."""
    name: NotRequired[str|None]
    startDate: NotRequired[str|None]
    endDate: NotRequired[str|None]


class AulaClosedDaysOverviewData(TypedDict):
    """An institution's closed days."""
    closedDays: NotRequired[List[AulaClosedDayData]|None]


class AulaInstitutionClosedDaysData(TypedDict):
    """One institution's closed days."""
    institutionCode: NotRequired[str|None]
    closedDaysOverview: NotRequired[AulaClosedDaysOverviewData|None]


class AulaClosedDaysData(TypedDict):
    """Each institution's closed days."""
    institutionClosedDays: NotRequired[List[AulaInstitutionClosedDaysData]|None]


class AulaGetClosedDaysResponse(TypedDict):
    """The answer to presence.getClosedDays."""
    data: AulaClosedDaysData
    status: AulaStatusData


class AulaOpeningHoursDayData(TypedDict):
    """An institution's hours on one day."""
    date: NotRequired[str|None]
    type: NotRequired[str|None]
    openTime: NotRequired[str|None]
    closeTime: NotRequired[str|None]


class AulaInstitutionOpeningHoursData(TypedDict):
    """One institution's hours, day by day."""
    institutionCode: NotRequired[str|None]
    openingHoursDto: NotRequired[List[AulaOpeningHoursDayData]|None]


class AulaOpeningHoursData(TypedDict):
    """Each institution's hours, day by day."""
    openingHoursOverviewDto: NotRequired[List[AulaInstitutionOpeningHoursData]|None]


class AulaGetOpeningHoursResponse(TypedDict):
    """The answer to presence.getOpeningHoursByInstitutionCodes."""
    data: AulaOpeningHoursData
    status: AulaStatusData
