"""Aula's answer to presence.getPresenceConfigurationByChildIds, as far as it is read."""

from typing import List, NotRequired, TypedDict

from .common_data import AulaStatusData


class AulaPresenceModuleData(TypedDict):
    """What may be done with one module of the presence module on a dashboard."""
    moduleType: NotRequired[str|None]
    permission: NotRequired[str|None]


class AulaPresenceDashboardModuleSettingsData(TypedDict):
    """The modules of one dashboard, such as the guardian's."""
    presenceDashboardContext: NotRequired[str|None]
    presenceModules: NotRequired[List[AulaPresenceModuleData]|None]


class AulaPresenceConfigurationData(TypedDict):
    """How the institution has set up the presence module."""
    dashboardModuleSettings: NotRequired[List[AulaPresenceDashboardModuleSettingsData]|None]


class AulaChildPresenceConfigurationData(TypedDict):
    """The presence module's set-up for one child."""
    presenceConfiguration: NotRequired[AulaPresenceConfigurationData|None]
    uniStudentId: NotRequired[int|None]


class AulaGetPresenceConfigurationByChildIdsResponse(TypedDict):
    """The answer, with each child's set-up."""
    data: List[AulaChildPresenceConfigurationData]
    status: AulaStatusData
