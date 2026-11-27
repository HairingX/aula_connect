"""The posts of Aula's news feed, and the days and hours an institution is open."""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import List


@dataclass
class AulaPostAttachment:
    """What is attached to a post: a file, a picture or a video."""
    name: str
    url: str | None
    """Where it is, for a while: Aula's links to files expire."""
    thumbnail_url: str | None
    """A small picture of it, for a picture or a video; None for a file."""
    is_media: bool


@dataclass
class AulaPost:
    """A post in Aula's news feed."""
    id: int
    title: str
    html: str
    """Its text, as Aula's HTML."""
    timestamp: datetime
    """When it was written."""
    publish_at: datetime | None
    edited_at: datetime | None
    expire_at: datetime | None
    is_important: bool
    important_from: date | None
    important_to: date | None
    author: str | None
    institution: str | None
    groups: List[str]
    """The groups it is shared with, by their names."""
    attachments: List[AulaPostAttachment]
    comment_count: int
    children: List[int] = field(default_factory=lambda: list[int]())
    """The institution profile ids of the user's children it concerns, as Aula relates it to them."""


@dataclass
class AulaPosts:
    """A page of posts, the newest first."""
    posts: List[AulaPost]
    last_seen: datetime | None
    """When the guardian last saw the posts in Aula; a post written later is new to them."""
    has_more: bool


@dataclass
class AulaClosedDay:
    """Days an institution is closed, such as a holiday, the last day included."""
    institution_code: str
    name: str
    start_date: date
    end_date: date


@dataclass
class AulaOpeningDay:
    """An institution's hours on one day."""
    institution_code: str
    day: date
    kind: str
    """Aula's kind of day: "general_opening_hours", "specific_opening_hours", "default_opening_hours" or "closed_day"."""
    open_time: time | None
    close_time: time | None

    @property
    def closed(self) -> bool:
        """Whether the institution is closed that day."""
        return self.kind == "closed_day"
