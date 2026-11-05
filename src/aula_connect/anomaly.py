"""What Aula sent that a client does not know or could not read, said without Aula's data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AnomalyKind(StrEnum):
    """The kinds of what a client met that it does not know or could not read."""

    UNKNOWN_NOTIFICATION_AREA = "unknown_notification_area"
    """A notification of an area the client does not know; the detail is the area."""
    UNREADABLE_RESPONSE = "unreadable_response"
    """An answer that could not be read; the detail is what was read, such as "notifications"."""
    API_VERSION_CHANGED = "api_version_changed"
    """Aula's API at a version the client was not made for; the detail is that version."""


@dataclass(frozen=True)
class Anomaly:
    """One kind of thing the client met, with what it was, and when it was last met."""

    kind: AnomalyKind
    detail: str
    """What was met: an area, a read or a version, never any of Aula's data."""
    last_seen: datetime
    """When it was last met, in UTC."""
