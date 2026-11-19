"""Aula's presence module (Komme/gå): a child's status, what a guardian may do, and how a child is reported sick."""

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum


class AulaPresenceStatus(IntEnum):
    """A child's presence status, as Aula numbers it."""
    NOT_PRESENT = 0
    SICK = 1
    REPORTED_ABSENT = 2
    PRESENT = 3
    FIELDTRIP = 4
    SLEEPING = 5
    SPARE_TIME_ACTIVITY = 6
    PHYSICAL_PLACEMENT = 7
    CHECKED_OUT = 8


class AulaPresenceModuleType(StrEnum):
    """A part of the presence module an institution switches on or off, by Aula's name."""
    PICKUP_TIMES = "pickup_times"
    DROP_OFF_TIME = "drop_off_time"
    DAILY_MESSAGE = "daily_message"
    REPORT_SICK = "report_sick"
    VACATION = "vacation"
    FIELD_TRIP = "field_trip"
    SPARE_TIME_ACTIVITY = "spare_time_activity"
    LOCATION = "location"
    SLEEP = "sleep"
    PICKUP_TYPE = "pickup_type"


class AulaPresencePermission(StrEnum):
    """What a guardian may do with a part of the presence module."""
    DEACTIVATED = "deactivated"
    READABLE = "readable"
    EDITABLE = "editable"


@dataclass
class AulaPresenceConfiguration:
    """What a child's guardian may see and do in the presence module, on the guardian's dashboard."""
    child_id: int
    """The child's institution profile id."""
    modules: dict[str, AulaPresencePermission] = field(default_factory=lambda: {})
    """The permission of each part, by Aula's name of it; a part Aula does not name is deactivated."""

    def permission(self, module: str) -> AulaPresencePermission:
        """The permission of the part `module`, such as `AulaPresenceModuleType.REPORT_SICK`."""
        return self.modules.get(module, AulaPresencePermission.DEACTIVATED)

    def editable(self, module: str) -> bool:
        """Whether the guardian may change the part `module`."""
        return self.permission(module) is AulaPresencePermission.EDITABLE


class AulaSickReportRoute(StrEnum):
    """Where a child is reported sick."""
    AULA = "aula"
    """Aula's own presence module."""
    TABULEX = "tabulex"
    """IST's Tabulex, through its widget in Aula."""
    NONE = "none"
    """Nowhere this library knows of."""
