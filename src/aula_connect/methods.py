"""The methods of Aula's API known by name, how each is asked, and the names Aula does not have.

A name not listed here may still be one Aula has; it is only not known to exist.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Evidence(StrEnum):
    """What shows that Aula has a method."""

    SEEN = "seen"
    """Aula answered it, as asked here, in this library's own reads."""
    USED = "used"
    """A maintained client of Aula's API asks it; not seen answered here."""


class Kind(StrEnum):
    """What a method does, and so whether it may be read."""

    READ = "read"
    """It only gets."""
    MESSAGES = "messages"
    """It gets the text of messages, which may be marked sensitive."""
    SECURE_DOCUMENTS = "secure_documents"
    """It gets secure documents, which may be marked sensitive."""
    TOKEN = "token"
    """It hands out a token, which is a credential."""
    WRITE = "write"
    """It changes something in Aula."""


@dataclass(frozen=True)
class Parameter:
    """A parameter a method is asked with."""

    name: str
    required: bool = True
    """Whether it is always sent; one that is not narrows or pages what Aula answers."""


@dataclass(frozen=True)
class AulaMethod:
    """A method of Aula's API, and how it is asked."""

    name: str
    verb: Literal["GET", "POST"]
    kind: Kind
    evidence: Evidence
    query: tuple[Parameter, ...] = ()
    """The parameters in the address, besides the method."""
    body: tuple[Parameter, ...] = ()
    """The keys of the JSON body a POST sends."""

    @property
    def readable(self) -> bool:
        """Whether it only gets, and nothing that may be marked sensitive."""
        return self.kind is Kind.READ


def _q(*names: str) -> tuple[Parameter, ...]:
    """Parameters by name, a name ending in `?` sent only at times."""
    return tuple(Parameter(name.removesuffix("?"), not name.endswith("?")) for name in names)


_R, _W, _M, _S, _T = Kind.READ, Kind.WRITE, Kind.MESSAGES, Kind.SECURE_DOCUMENTS, Kind.TOKEN
_SEEN, _USED = Evidence.SEEN, Evidence.USED

METHODS: Mapping[str, AulaMethod] = {
    method.name: method
    for method in (
        AulaMethod("aulaToken.getAulaToken", "GET", _T, _SEEN, _q("widgetId")),
        AulaMethod("calendar.addVacation", "POST", _W, _USED, (), _q("childIds", "intervals", "comment")),
        AulaMethod("calendar.getBirthdayEventsForGroup", "GET", _R, _USED, _q("groupId", "start", "end")),
        AulaMethod("calendar.getBirthdayEventsForInstitutions", "GET", _R, _SEEN, _q("instCodes[]", "start", "end")),
        AulaMethod("calendar.getDailyAggregatedEvents", "GET", _R, _USED, _q("InstProfileIds[]", "Start", "End")),
        AulaMethod("calendar.getDailyEventCountForGroup", "GET", _R, _USED, _q("GroupId", "Start", "End")),
        AulaMethod("calendar.getEventById", "GET", _R, _USED, _q("eventId", "occurrenceDateTime?")),
        AulaMethod("calendar.getEventTypes", "GET", _R, _USED, _q("Type", "FilterInstitutionCodes[]?")),
        AulaMethod("calendar.getEventsByProfileIdsAndResourceIds", "POST", _R, _SEEN, (), _q("instProfileIds", "resourceIds", "start", "end")),
        AulaMethod("calendar.getEventsForInstitutions", "GET", _R, _USED, _q("Start", "End", "InstCodes[]")),
        AulaMethod("calendar.getImportantDates", "GET", _R, _USED, _q("limit", "includeToday")),
        AulaMethod("calendar.geteventsbygroupid", "GET", _R, _USED, _q("groupId", "start", "end")),
        AulaMethod("comments.getComments", "GET", _R, _USED, _q("ParentType", "ParentId", "Limit")),
        AulaMethod("commonFiles.getCommonFiles", "GET", _R, _USED, _q("index", "limit", "institutionCodes[]")),
        AulaMethod("consents.getConsentResponses", "GET", _R, _USED, _q("institutionProfileIds[]")),
        AulaMethod("documents.getSecureDocuments", "POST", _S, _USED, (), _q("index", "limit", "filterInstitutionProfileIds")),
        AulaMethod("gallery.getAlbums", "GET", _R, _USED, _q("index", "limit", "sortOn", "orderDirection", "filterBy", "filterInstProfileIds[]")),
        AulaMethod("gallery.getMedia", "GET", _R, _USED, _q("albumId", "index", "limit", "sortOn", "orderDirection", "filterBy", "filterInstProfileIds[]")),
        AulaMethod("gallery.getMediaById", "GET", _R, _USED, _q("id")),
        AulaMethod("gallery.getMediaByInstitutionProfileId", "GET", _R, _USED, _q("institutionProfileId", "Limit")),
        AulaMethod("groups.getGroupById", "GET", _R, _USED, _q("groupId")),
        AulaMethod("groups.getGroupsByContext", "GET", _R, _USED, _q("childInstitutionProfileIds[]?", "institutionCodes[]?")),
        AulaMethod("groups.getMembershipsLight", "GET", _R, _USED, _q("groupId", "portalRoles[]?")),
        AulaMethod("messaging.getAutoReply", "GET", _R, _USED),
        AulaMethod("messaging.getCommonInboxes", "GET", _R, _USED, _q("InstitutionProfileIds[]?")),
        AulaMethod("messaging.getFolders", "GET", _R, _USED, _q("IncludeDeletedFolders")),
        AulaMethod("messaging.getMessageInfoLight", "GET", _M, _USED, _q("ThreadId", "MessageId")),
        AulaMethod("messaging.getMessagesForThread", "GET", _M, _SEEN, _q("threadId", "page")),
        AulaMethod("messaging.getThreads", "GET", _M, _SEEN, _q("sortOn", "orderDirection", "page")),
        AulaMethod("messaging.getThreadsInBundle", "GET", _M, _USED, _q("BundleId")),
        AulaMethod("messaging.setLastReadMessage", "POST", _W, _USED, (), _q("threadId", "messageId", "commonInboxId", "otpInboxId")),
        AulaMethod("notifications.getNotificationSettingsForActiveProfile", "GET", _R, _USED),
        AulaMethod("notifications.getNotificationsForActiveProfile", "GET", _R, _SEEN, _q("activeChildrenIds[]", "activeInstitutionCodes[]")),
        AulaMethod("posts.getAllPosts", "GET", _R, _USED, _q("parent", "index", "limit", "institutionProfileIds[]")),
        AulaMethod("posts.getById", "GET", _R, _USED, _q("id")),
        AulaMethod("presence.getActivityOverview", "GET", _R, _USED, _q("institutionProfileIds[]", "week", "year")),
        AulaMethod("presence.getDailyOverview", "GET", _R, _SEEN, _q("childIds[]")),
        AulaMethod("presence.getPickupResponsibles", "GET", _R, _USED, _q("uniStudentIds[]")),
        AulaMethod("presence.getPresenceConfigurationByChildIds", "GET", _R, _USED, _q("childIds[]")),
        AulaMethod("presence.getPresenceRegistrationDetail", "GET", _R, _USED, _q("id")),
        AulaMethod("presence.getPresenceRegistrations", "GET", _R, _USED, _q("institutionProfileIds[]", "fromDate", "toDate")),
        AulaMethod("presence.getPresenceStates", "GET", _R, _USED, _q("institutionProfileIds[]?")),
        AulaMethod("presence.getPresenceTemplates", "GET", _R, _USED, _q("filterInstitutionProfileIds[]", "fromDate", "toDate")),
        AulaMethod("presence.getVacationRegistrationsByChildren", "GET", _R, _USED, _q("childIds[]")),
        AulaMethod("presence.updatePresenceTemplate", "POST", _W, _USED, (), _q("institutionProfileId", "byDate", "presenceActivity", "comment", "repeatPattern", "expiresAt", "id?")),
        AulaMethod("presence.updateStatusByInstitutionProfileIds", "POST", _W, _USED, (), _q("institutionProfileIds", "status")),
        AulaMethod("profiles.getContactParents", "GET", _R, _USED, _q("page", "order")),
        AulaMethod("profiles.getContactlist", "GET", _R, _USED, _q("groupId", "filter", "field", "page", "order")),
        AulaMethod("profiles.getProfileContext", "GET", _R, _SEEN, _q("portalrole")),
        AulaMethod("profiles.getProfileMasterData", "GET", _R, _SEEN, _q("instProfileIds[]", "fromAdministration")),
        AulaMethod("profiles.getProfilesByLogin", "GET", _R, _SEEN),
        AulaMethod("profiles.keepAlive", "GET", _W, _USED),
        AulaMethod("search.findGeneric", "GET", _M, _USED, _q("Text", "Limit", "Offset", "DocTypeCount", "DocType?")),
        AulaMethod("search.findGroups", "GET", _R, _USED, _q("text", "limit")),
        AulaMethod("search.findMessage", "POST", _M, _USED, (), _q("text", "typeahead", "exactTerm", "activeChildrenInstitutionProfileIds", "institutionCodes", "limit", "offset", "commonInboxID", "filterBy", "sortBy", "sortDirection", "threadSubject", "messageContent", "fromDate", "toDate", "threadCreators", "participants", "hasAttachments")),
        AulaMethod("search.findProfilesAndGroups", "GET", _R, _USED, _q("Text", "Limit", "Typeahead")),
        AulaMethod("search.findRecipients", "GET", _R, _USED, _q("Text", "Limit", "TypeAhead", "DocTypes?", "PortalRoles?")),
    )
}
"""Every method known to exist, by its name as Aula spells it."""

WRONG_NAMES: Mapping[str, str] = {
    "calendar.getEventDetail": "calendar.getEventById",
    "presence.getVacationRegistrations": "presence.getVacationRegistrationsByChildren",
    "profiles.getContactList": "profiles.getContactlist",
    "search.searchGroups": "search.findGroups",
    "secureDocument.getCommonFiles": "commonFiles.getCommonFiles",
    "secureDocument.getSecureDocuments": "documents.getSecureDocuments",
}
"""Names Aula has no method by, each with the name of the method meant."""

_BY_LOWER = {name.lower(): method for name, method in METHODS.items()}


def known(name: str) -> AulaMethod | None:
    """The method known by `name`, spelt as Aula spells it; None where none is."""
    return METHODS.get(name)


def alike(name: str) -> AulaMethod | None:
    """The method known by `name` in any case, as Aula spells it; None where none is.

    Aula tells names apart by their case: `profiles.getContactList` is no method, where
    `profiles.getContactlist` is.
    """
    return _BY_LOWER.get(name.lower())


def meant(name: str) -> str | None:
    """The method meant by `name` where Aula has none by it; else None."""
    return WRONG_NAMES.get(name)
