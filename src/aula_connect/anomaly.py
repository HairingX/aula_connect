"""What Aula sent that a client does not know or could not read, said without Aula's data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AnomalyKind(StrEnum):
    """The kinds of what a client met that it does not know or could not read.

    A later minor version may add a kind, so a caller handles one it does not know; a kind is
    never renamed or removed, and its value stays the same.
    """

    UNKNOWN_NOTIFICATION_AREA = "unknown_notification_area"
    """A notification of an area the client does not know; the detail is the area's name, or
    "<missing>" or "<unrecognised>" where Aula sent none or something that is no name."""
    UNREADABLE_RESPONSE = "unreadable_response"
    """An answer that could not be read; the detail is what was read, in words, such as
    "notifications" or "weekly plans"."""
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
