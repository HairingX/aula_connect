"""What of Aula's catalog of methods that only read is asked once, and with what.

The values are those a maintained client of Aula's API sends each method; the ids are the
account's own: its children's institution profiles, the guardian's own, the institutions' codes
and the children's main groups.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from .methods import METHODS

ITEMS = 3
"""How many of a list's items are read one by one, the first in it first."""

LIMIT = 20
"""How many items a list is asked for."""

Params = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Account:
    """The ids of an account the catalog's methods are asked about."""

    children: Sequence[int]
    """The children's institution profile ids."""
    own: Sequence[int]
    """The guardian's own institution profile ids."""
    profiles: Sequence[int]
    """The guardian's institution profile ids and the children's."""
    institutions: Sequence[str]
    """The institutions' codes."""
    groups: Sequence[int]
    """The children's main groups' ids."""
    start: datetime.date
    end: datetime.date


NO_VALUES = {
    "search.findGroups": "it searches for a text",
    "search.findProfilesAndGroups": "it searches for a text",
    "search.findRecipients": "it searches for a text",
    "groups.getMemberships": "it names the other members of a group, read in short already",
    "messaging.getOtpInboxesForLoggedInProfile": "Aula's own web app asks it only of a group home's login, and refuses a guardian",
}
"""Why a method that only reads is not asked, by its name."""

UNKNOWN_VALUES = "it is asked about an item, or with values, the account's reads do not give"
"""Why another method that only reads is not asked."""

FOLLOWED = frozenset(
    {
        "posts.getById",
        "comments.getComments",
        "gallery.getMedia",
        "gallery.getMediaById",
        "presence.getVacationRegistrationResponse",
    }
)
"""The methods asked of the items of a list another answers with."""


def _many(name: str, values: Iterable[object]) -> Params:
    return tuple((name, str(value)) for value in values)


def plan(account: Account) -> list[tuple[str, Params]]:
    """Returns each method of the catalog that only reads, with its parameters, in its order."""
    day = account.start.isoformat()
    last = account.end.isoformat()
    kids, everyone = account.children, account.profiles
    asked: list[tuple[str, Params]] = [
        ("calendar.getDailyAggregatedEvents", (*_many("InstProfileIds[]", kids), ("Start", day), ("End", last))),
        ("calendar.getEventTypes", (("Type", "all"),)),
        ("calendar.getImportantDates", (("limit", "10"), ("includeToday", "true"))),
        ("commonFiles.getCommonFiles", (("index", "0"), ("limit", str(LIMIT)), *_many("institutionCodes[]", account.institutions))),
        ("consents.getConsentResponses", _many("institutionProfileIds[]", everyone)),
        (
            "gallery.getAlbums",
            (
                ("index", "0"),
                ("limit", str(LIMIT)),
                ("sortOn", "createdAt"),
                ("orderDirection", "desc"),
                ("filterBy", "all"),
                *_many("filterInstProfileIds[]", everyone),
            ),
        ),
        ("groups.getGroupsByContext", _many("childInstitutionProfileIds[]", kids)),
        ("CalendarFeed.getFeedConfigurations", ()),
        ("CalendarFeed.getPolicyAnswer", ()),
        ("messaging.getCommonInboxes", _many("institutionProfileIds[]", account.own)),
        ("messaging.getFolders", (("IncludeDeletedFolders", "false"),)),
        ("Notifications.getNotificationSettingsForActiveProfile", ()),
        (
            "posts.getAllPosts",
            (("parent", "profile"), ("index", "0"), ("limit", str(LIMIT)), *_many("institutionProfileIds[]", everyone)),
        ),
        ("presence.getClosedDays", _many("institutionCodes[]", account.institutions)),
        ("presence.getGeneralOpeningHours", _many("institutionCodes[]", account.institutions)),
        (
            "presence.getOpeningHoursByInstitutionCodes",
            (*_many("institutionCodes[]", account.institutions), ("startDate", day), ("endDate", last)),
        ),
        ("presence.getPickupResponsibles", _many("uniStudentIds[]", kids)),
        ("presence.getPresenceConfigurationByChildIds", _many("childIds[]", kids)),
        ("presence.getPresenceStates", _many("institutionProfileIds[]", kids)),
        ("presence.getPresenceTemplates", (*_many("filterInstitutionProfileIds[]", kids), ("fromDate", day), ("toDate", last))),
        ("presence.getSpecificOpeningHourOverview", _many("institutionCodes[]", account.institutions)),
        ("presence.getVacationAnnouncementsByChildren", _many("childIds[]", kids)),
        ("presence.getVacationRegistrationsByChildren", _many("childIds[]", kids)),
    ]
    for group in account.groups:
        asked += [
            ("calendar.getBirthdayEventsForGroup", (("groupId", str(group)), ("start", day), ("end", last))),
            ("calendar.getDailyEventCountForGroup", (("GroupId", str(group)), ("Start", day), ("End", last))),
            ("calendar.geteventsbygroupid", (("groupId", str(group)), ("start", day), ("end", last))),
            ("groups.getGroupById", (("groupId", str(group)),)),
            ("groups.getMembershipsLight", (("groupId", str(group)),)),
            (
                "profiles.getContactlist",
                (("groupId", str(group)), ("filter", "guardian"), ("field", "name"), ("page", "1"), ("order", "asc")),
            ),
        ]
    return asked


def _ids(data: Any, key: str) -> list[str]:
    """The ids of the first items of the list `data` is, or holds under `key`."""
    listed: Any = cast(dict[str, Any], data).get(key) if isinstance(data, dict) else data
    if not isinstance(listed, list):
        return []
    items = cast(list[Any], listed)
    found = [cast(dict[str, Any], item).get("id") for item in items if isinstance(item, dict)]
    return [str(item) for item in found if item is not None][:ITEMS]


def _commented(data: Any) -> set[str]:
    """The ids of the posts in `data` that have comments."""
    posts = cast(dict[str, Any], data).get("posts") if isinstance(data, dict) else None
    items = [cast(dict[str, Any], item) for item in cast(list[Any], posts) if isinstance(item, dict)] if isinstance(posts, list) else []
    return {str(item.get("id")) for item in items if isinstance(item.get("commentCount"), int) and item["commentCount"] > 0}


def then(method: str, data: Any, account: Account) -> list[tuple[str, Params]]:
    """Returns what is asked of the items `method` answered with `data`, one by one."""
    match method:
        case "posts.getAllPosts":
            # Aula refuses the comments of a post that has none, as for one that allows none.
            commented = _commented(data)
            return [
                asked
                for post in _ids(data, "posts")
                for asked in (
                    ("posts.getById", (("id", post),)),
                    *(
                        [("comments.getComments", (("parentType", "Post"), ("parentId", post), ("startIndex", "0"), ("limit", str(LIMIT))))]
                        if post in commented
                        else []
                    ),
                )
            ]
        case "gallery.getAlbums":
            return [
                (
                    "gallery.getMedia",
                    (
                        ("albumId", album),
                        ("index", "0"),
                        ("limit", str(LIMIT)),
                        ("sortOn", "uploadedAt"),
                        ("orderDirection", "desc"),
                        ("filterBy", "all"),
                        *_many("filterInstProfileIds[]", account.profiles),
                    ),
                )
                for album in _ids(data, "albums")[:1]
            ]
        case "presence.getVacationRegistrationsByChildren":
            groups = cast(list[Any], data) if isinstance(data, list) else []
            requests: list[dict[str, Any]] = []
            for group in groups:
                if isinstance(group, dict):
                    listed = cast(list[Any], cast(dict[str, Any], group).get("vacationRegistrations") or [])
                    requests += [cast(dict[str, Any], item) for item in listed if isinstance(item, dict)]
            found = [item.get("responseId") for item in requests]
            return [
                ("presence.getVacationRegistrationResponse", (("vacationRegistrationResponseId", str(response)),))
                for response in found[:ITEMS]
                if response is not None
            ]
        case "gallery.getMedia":
            return [("gallery.getMediaById", (("id", media),)) for media in _ids(data, "results")]
        case _:
            return []


def readable() -> list[str]:
    """The names of the catalog's methods that only read, in its order."""
    return [name for name, method in METHODS.items() if method.readable]
