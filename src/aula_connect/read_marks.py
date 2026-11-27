"""The marks Aula keeps of what the user has seen, read twice to tell whether reading moves them.

A read of the news feed, the message threads or the notifications answers with what Aula holds
the user has seen: when they last saw the posts, which threads are read and to which message,
and which notifications are still waiting. Read again a moment later, the same request tells
whether the first read moved a mark - which would mean that reading tells Aula something was
seen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

RECHECK_AFTER = timedelta(seconds=5)
"""How long after the first read of a mark it is read again, at the least."""


def _data(response: Any) -> Any:
    return cast(dict[str, Any], response).get("data") if isinstance(response, dict) else None


def _items(value: Any) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], item) for item in cast(list[Any], value) if isinstance(item, dict)] if isinstance(value, list) else []


def _posts(response: Any) -> dict[str, Any]:
    data = _data(response)
    return {"feed": cast(dict[str, Any], data).get("profileLastSeenPostDate") if isinstance(data, dict) else None}


def _threads(response: Any) -> dict[str, Any]:
    data = _data(response)
    threads = _items(cast(dict[str, Any], data).get("threads")) if isinstance(data, dict) else []
    return {str(thread.get("id")): (thread.get("read") is True, thread.get("lastReadMessageId")) for thread in threads}


def _notifications(response: Any) -> dict[str, Any]:
    return {str(item.get("notificationId")): True for item in _items(_data(response))}


def _feed_moved(before: Any, after: Any) -> bool:
    return before != after


def _thread_read(before: Any, after: Any) -> bool:
    if after is None:
        return False
    (was_read, was_last), (is_read, is_last) = before, after
    return (is_read and not was_read) or (is_last is not None and is_last != was_last)


def _gone(before: Any, after: Any) -> bool:
    return after is None


@dataclass(frozen=True)
class Watched:
    """A method whose answer holds marks of what the user has seen."""

    method: str
    """The Aula API method."""
    mark: str
    """What is watched, in words."""
    marks: Callable[[Any], dict[str, Any]]
    """Each mark in an answer, by what it is on."""
    summary: Callable[[dict[str, Any]], str | int | None]
    """The marks of an answer told as one value: a time, or how many."""
    moved: Callable[[Any, Any], bool]
    """Whether a mark moved towards seen, from its value in the first answer to that in the second; None where it is gone."""


WATCHED: tuple[Watched, ...] = (
    Watched(
        "posts.getAllPosts",
        "when the posts were last seen",
        _posts,
        lambda marks: cast(str | None, marks.get("feed")),
        _feed_moved,
    ),
    Watched(
        "messaging.getThreads",
        "threads not read",
        _threads,
        lambda marks: sum(1 for read, _ in marks.values() if not read),
        _thread_read,
    ),
    Watched(
        "notifications.getNotificationsForActiveProfile",
        "notifications waiting",
        _notifications,
        len,
        _gone,
    ),
)
"""The methods whose answers hold marks of what the user has seen, read twice by `read_everything`."""


@dataclass(frozen=True)
class ReadMark:
    """What two reads of a method a moment apart told of the marks of what the user has seen."""

    method: str
    mark: str
    before: str | int | None
    """The marks in the first answer, as one value."""
    after: str | int | None
    """The marks in the second answer, as one value."""
    moved: int
    """How many marks moved towards seen between the reads."""
    seconds: float
    """The time between the reads."""

    def as_dict(self) -> dict[str, Any]:
        """The result as JSON."""
        return {
            "method": self.method,
            "mark": self.mark,
            "before": self.before,
            "after": self.after,
            "moved": self.moved,
            "seconds": round(self.seconds, 1),
        }


def compare(watched: Watched, first: Any, second: Any, seconds: float) -> ReadMark:
    """What the marks in `first` and `second`, two answers to `watched`'s method, tell."""
    before, after = watched.marks(first), watched.marks(second)
    moved = sum(1 for key, value in before.items() if watched.moved(value, after.get(key)))
    return ReadMark(watched.method, watched.mark, watched.summary(before), watched.summary(after), moved, seconds)
