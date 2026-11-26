"""The methods of Aula's API known by name, and how each is asked.

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
    WEB = "web"
    """Aula's own web app asks it; not seen answered here."""


class Kind(StrEnum):
    """What a method does, and so whether it may be read."""

    READ = "read"
    """It only gets."""
    MESSAGES = "messages"
    """It gets the text of messages, which may be marked sensitive."""
    SECURE_DOCUMENTS = "secure_documents"
    """It gets secure documents, which may be marked sensitive."""
    TOKEN = "token"
    """It hands out a token, which is a credential, or checks one."""
    PERSONAL = "personal"
    """It gets a person's answers to Aula's questions and the like, which may be sensitive."""
    STAFF = "staff"
    """It gets what only the institution's staff, administrators or devices see; Aula refuses a
    guardian."""
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
_P, _STAFF = Kind.PERSONAL, Kind.STAFF
_SEEN, _USED, _WEB = Evidence.SEEN, Evidence.USED, Evidence.WEB

_ALL: tuple[AulaMethod, ...] = (
    AulaMethod("aulaToken.getAulaToken", "GET", _T, _SEEN, _q("widgetId")),
    AulaMethod("calendar.addVacation", "POST", _W, _USED, (), _q("childIds", "intervals", "comment")),
    AulaMethod("calendar.blockTimeSlot", "POST", _W, _WEB),
    AulaMethod("calendar.checkConflictEventForAttendees", "POST", _W, _WEB),
    AulaMethod("calendar.createRepeatingEvent", "POST", _W, _WEB),
    AulaMethod("calendar.createSimpleEvent", "POST", _W, _WEB),
    AulaMethod("calendar.createTimeSlotEvent", "POST", _W, _WEB),
    AulaMethod("calendar.createVacationRequest", "POST", _W, _WEB),
    AulaMethod("calendar.deleteEvent", "POST", _W, _WEB, (), _q("id")),
    AulaMethod("calendar.getBirthdayEventsForGroup", "GET", _R, _SEEN, _q("groupId", "start", "end")),
    AulaMethod("calendar.getBirthdayEventsForInstitutions", "GET", _R, _SEEN, _q("instCodes[]", "start", "end")),
    AulaMethod("calendar.getDailyAggregatedEvents", "GET", _R, _SEEN, _q("InstProfileIds[]", "Start", "End")),
    AulaMethod("calendar.getDailyEventCountForGroup", "GET", _R, _SEEN, _q("GroupId", "Start", "End")),
    AulaMethod("calendar.getDelegatedAccesses", "GET", _STAFF, _WEB),
    AulaMethod("calendar.getDelegatedContext", "GET", _STAFF, _WEB),
    AulaMethod("calendar.getEventById", "GET", _R, _USED, _q("eventId", "occurrenceDateTime?")),
    AulaMethod("calendar.getEventsByGroupHomeChildPairs", "POST", _R, _WEB),
    AulaMethod("calendar.geteventsbygroupid", "GET", _R, _SEEN, _q("groupId", "start", "end")),
    AulaMethod("calendar.getEventsByProfileIdsAndResourceIds", "POST", _R, _SEEN, (), _q("instProfileIds", "resourceIds", "start", "end")),
    AulaMethod("calendar.getEventsForInstitutions", "GET", _STAFF, _USED, _q("Start", "End", "InstCodes[]")),
    AulaMethod("calendar.getEventTypes", "GET", _R, _SEEN, _q("Type", "FilterInstitutionCodes[]?")),
    AulaMethod("calendar.getFutureVacationRequests", "GET", _R, _WEB),
    AulaMethod("calendar.getGuardiansWithPendingVacationRequestResponses", "GET", _STAFF, _WEB),
    AulaMethod("calendar.getImportantDates", "GET", _R, _SEEN, _q("limit", "includeToday")),
    AulaMethod("calendar.getInstitutionProfilesWithDelegatedAccess", "GET", _STAFF, _WEB),
    AulaMethod("calendar.getTimeSlotResponse", "GET", _R, _WEB),
    AulaMethod("calendar.getVacationRequestResponses", "GET", _STAFF, _WEB),
    AulaMethod("calendar.removeAttendeeFromEvent", "POST", _W, _WEB),
    AulaMethod("calendar.removeBlockingOrResponseToTimeSlot", "POST", _W, _WEB),
    AulaMethod("calendar.requestVacation", "POST", _W, _WEB),
    AulaMethod("calendar.respondToEvent", "POST", _W, _WEB),
    AulaMethod("calendar.respondToSimpleEvent", "POST", _W, _WEB),
    AulaMethod("calendar.respondToTimeSlotEvent", "POST", _W, _WEB),
    AulaMethod("calendar.respondToVacationRegistrationRequest", "POST", _W, _WEB, (), _q("vacationRegistrationResponseId", "childId", "days", "comment")),
    AulaMethod("calendar.setDelegatedAccesses", "POST", _W, _WEB),
    AulaMethod("calendar.setDelegatedContext", "POST", _W, _WEB),
    AulaMethod("calendar.updateEventResources", "POST", _W, _WEB),
    AulaMethod("calendar.updateLessonEvent", "POST", _W, _WEB),
    AulaMethod("calendar.updateRepeatingEvent", "POST", _W, _WEB),
    AulaMethod("calendar.updateResponseToTimeSlotEvent", "POST", _W, _WEB),
    AulaMethod("calendar.updateSimpleEvent", "POST", _W, _WEB),
    AulaMethod("calendar.updateTimeSlotEvent", "POST", _W, _WEB),
    AulaMethod("calendar.updateVacationRequest", "POST", _W, _WEB),
    AulaMethod("calendarAdmin.deleteEvent", "POST", _W, _WEB),
    AulaMethod("calendarAdmin.getEventsByProfileId", "GET", _STAFF, _WEB),
    AulaMethod("CalendarFeed.createFeedConfiguration", "POST", _W, _WEB),
    AulaMethod("calendarFeed.getEventTypesRelevantForPortalRole", "GET", _R, _WEB),
    AulaMethod("CalendarFeed.getFeedConfigurations", "GET", _R, _WEB),
    AulaMethod("CalendarFeed.getPolicyAnswer", "GET", _R, _WEB),
    AulaMethod("CalendarFeed.removeFeedConfiguration", "POST", _W, _WEB),
    AulaMethod("CalendarFeed.setPolicyAnswer", "POST", _W, _WEB),
    AulaMethod("CalendarFeed.updateFeedConfiguration", "POST", _W, _WEB),
    AulaMethod("centralConfiguration.createAuthorizedFileFormat", "POST", _W, _WEB),
    AulaMethod("centralConfiguration.getAuthorizedFileFormats", "GET", _STAFF, _WEB),
    AulaMethod("CentralConfiguration.getDataPolicy", "GET", _R, _WEB),
    AulaMethod("centralConfiguration.getLoginImportantInformation", "GET", _R, _WEB),
    AulaMethod("centralConfiguration.getMaxFileSize", "GET", _STAFF, _WEB),
    AulaMethod("CentralConfiguration.getOpenDataPolicy", "GET", _R, _WEB),
    AulaMethod("centralConfiguration.removeAuthorizedFileFormat", "POST", _W, _WEB),
    AulaMethod("centralConfiguration.setMaxFileSize", "POST", _W, _WEB),
    AulaMethod("comments.acceptReport", "POST", _W, _WEB),
    AulaMethod("comments.addComment", "POST", _W, _WEB),
    AulaMethod("comments.deleteComment", "POST", _W, _WEB),
    AulaMethod("comments.getComments", "GET", _R, _USED, _q("parentType", "parentId", "startIndex", "limit")),
    AulaMethod("comments.getReportedComments", "POST", _STAFF, _WEB),
    AulaMethod("comments.rejectReport", "POST", _W, _WEB),
    AulaMethod("comments.reportComment", "POST", _W, _WEB),
    AulaMethod("comments.updateComment", "POST", _W, _WEB),
    AulaMethod("commentsAdmin.getAllCommentsForUser", "GET", _STAFF, _WEB),
    AulaMethod("commentsAdmin.hardDeleteComment", "POST", _W, _WEB),
    AulaMethod("commonFiles.getCommonFiles", "GET", _R, _SEEN, _q("index", "limit", "institutionCodes[]")),
    AulaMethod("commonFiles.getPersonalDataPolicies", "GET", _R, _WEB),
    AulaMethod("commonFilesAdmin.createCommonFile", "POST", _W, _WEB),
    AulaMethod("commonFilesAdmin.deleteCommonFile", "POST", _W, _WEB),
    AulaMethod("commonFilesAdmin.getCommonFileById", "GET", _STAFF, _WEB),
    AulaMethod("commonFilesAdmin.getInstitutionDataPolicyName", "GET", _STAFF, _WEB),
    AulaMethod("commonFilesAdmin.titleExistsOnInstitution", "GET", _W, _WEB),
    AulaMethod("commonFilesAdmin.updateCommonFile", "POST", _W, _WEB),
    AulaMethod("consents.getConsentResponses", "GET", _R, _SEEN, _q("institutionProfileIds[]")),
    AulaMethod("consents.updateConsentResponses", "POST", _W, _WEB),
    AulaMethod("consentsAdmin.deleteConsentResponseAnswersByInstitutionProfileId", "POST", _W, _WEB),
    AulaMethod("consentsAdmin.getConsentResponseRevisionHistory", "GET", _STAFF, _WEB),
    AulaMethod("dashboards.getAdminDashboardConfiguration", "GET", _STAFF, _WEB),
    AulaMethod("dashboards.getWidgetsByIds", "GET", _STAFF, _WEB),
    AulaMethod("dashboardsAdmin.getAllModules", "GET", _STAFF, _WEB),
    AulaMethod("dashboardsAdmin.getAllWidgets", "GET", _STAFF, _WEB),
    AulaMethod("documents.createArchiveForMultipleSecureDocuments", "POST", _W, _WEB),
    AulaMethod("documents.createExternalSecureFile", "POST", _W, _WEB),
    AulaMethod("documents.createInternalSecureDocument", "POST", _W, _WEB),
    AulaMethod("documents.deleteDocument", "POST", _W, _WEB),
    AulaMethod("documents.exportDocumentsToEsdh", "POST", _W, _WEB),
    AulaMethod("Documents.getDocumentCategoriesAndTemplates", "GET", _S, _WEB),
    AulaMethod("Documents.getDocumentRevision", "GET", _S, _WEB),
    AulaMethod("Documents.getDocumentRevisions", "GET", _S, _WEB),
    AulaMethod("documents.getExternalSecureFile", "GET", _S, _WEB),
    AulaMethod("Documents.getImplicitSharings", "POST", _S, _WEB),
    AulaMethod("documents.getInternalSecureDocument", "GET", _S, _WEB),
    AulaMethod("documents.getMaxDocumentsPerExport", "GET", _S, _WEB),
    AulaMethod("Documents.getSecureDocuments", "POST", _S, _USED, (), _q("index", "limit", "filterInstitutionProfileIds")),
    AulaMethod("Documents.getShareableSecureDocuments", "POST", _S, _WEB),
    AulaMethod("documents.markAsRead", "POST", _W, _WEB),
    AulaMethod("documents.markAsUnread", "POST", _W, _WEB),
    AulaMethod("documents.removeOwnSharings", "POST", _W, _WEB),
    AulaMethod("documents.trackCreateArchiveForMultipleSecureDocumentsRequest", "POST", _W, _WEB),
    AulaMethod("documents.updateExternalSecureFile", "POST", _W, _WEB),
    AulaMethod("documents.updateInternalSecureDocument", "POST", _W, _WEB),
    AulaMethod("documents.updateLockedStatus", "POST", _W, _WEB),
    AulaMethod("documents.updateSharings", "POST", _W, _WEB),
    AulaMethod("documentsAdmin.deleteDocuments", "POST", _W, _WEB),
    AulaMethod("documentsAdmin.getDeletedSecureDocuments", "POST", _STAFF, _WEB),
    AulaMethod("documentsAdmin.getSecureDocumentsRegardingInstitutionProfile", "GET", _STAFF, _WEB),
    AulaMethod("documentsAdmin.restoreDeletedDocument", "POST", _W, _WEB),
    AulaMethod("EsdhDataExportAdmin.addEsdhDataExportRecipient", "POST", _W, _WEB),
    AulaMethod("EsdhDataExportAdmin.deleteEsdhDataExportRecipient", "POST", _W, _WEB),
    AulaMethod("EsdhDataExportAdmin.getEsdhDataExportConfiguration", "GET", _STAFF, _WEB),
    AulaMethod("EsdhDataExportAdmin.getExportData", "GET", _STAFF, _WEB),
    AulaMethod("EsdhDataExportAdmin.getExportDataForMunicipality", "GET", _STAFF, _WEB),
    AulaMethod("EsdhDataExportAdmin.getRecipientNames", "GET", _STAFF, _WEB),
    AulaMethod("EsdhDataExportAdmin.journalizeDocuments", "POST", _W, _WEB),
    AulaMethod("EsdhDataExportAdmin.markDocumentsForManualTransfer", "POST", _W, _WEB),
    AulaMethod("EsdhDataExportAdmin.resendDocuments", "POST", _W, _WEB),
    AulaMethod("EsdhDataExportAdmin.updateEsdhDataExportRecipient", "POST", _W, _WEB),
    AulaMethod("files.completeMultipartUploading", "POST", _W, _WEB),
    AulaMethod("files.createAttachments", "POST", _W, _WEB),
    AulaMethod("files.createDocumentLinks", "POST", _W, _WEB),
    AulaMethod("files.updateAttachments", "POST", _W, _WEB),
    AulaMethod("gallery.acceptReportedMedia", "POST", _W, _WEB),
    AulaMethod("gallery.createAlbum", "POST", _W, _WEB),
    AulaMethod("gallery.createMedia", "POST", _W, _WEB),
    AulaMethod("gallery.deleteAlbums", "POST", _W, _WEB),
    AulaMethod("gallery.deleteMedia", "POST", _W, _WEB),
    AulaMethod("gallery.getAlbums", "GET", _R, _SEEN, _q("index", "limit", "sortOn", "orderDirection", "filterBy", "filterInstProfileIds[]")),
    AulaMethod("gallery.getMedia", "GET", _R, _SEEN, _q("albumId", "index", "limit", "sortOn", "orderDirection", "filterBy", "filterInstProfileIds[]")),
    AulaMethod("gallery.getMediaById", "GET", _R, _SEEN, _q("id")),
    AulaMethod("gallery.getReportedMedia", "POST", _STAFF, _WEB),
    AulaMethod("gallery.rejectReportedMedia", "POST", _W, _WEB),
    AulaMethod("gallery.reportMedia", "POST", _W, _WEB),
    AulaMethod("gallery.updateAlbum", "POST", _W, _WEB),
    AulaMethod("gallery.updateMedia", "POST", _W, _WEB),
    AulaMethod("galleryAdmin.deleteMedia", "POST", _W, _WEB),
    AulaMethod("galleryAdmin.getAlbums", "GET", _STAFF, _WEB),
    AulaMethod("galleryAdmin.getMedia", "GET", _STAFF, _WEB),
    AulaMethod("galleryAdmin.getMediaByInstitutionProfileId", "GET", _STAFF, _WEB),
    AulaMethod("genericAdmin.getInstitutions", "GET", _STAFF, _WEB),
    AulaMethod("genericAdmin.getMunicipalities", "GET", _STAFF, _WEB),
    AulaMethod("groups.createGroup", "POST", _W, _WEB),
    AulaMethod("groups.deleteGroupMemberships", "POST", _W, _WEB),
    AulaMethod("groups.getDirectMemberships", "GET", _STAFF, _WEB),
    AulaMethod("groups.getGroupById", "GET", _R, _SEEN, _q("groupId")),
    AulaMethod("groups.getGroupsByContext", "GET", _R, _SEEN, _q("childInstitutionProfileIds[]?", "institutionCodes[]?")),
    AulaMethod("groups.getMemberships", "GET", _R, _WEB, _q("groupId", "portalRoles[]?")),
    AulaMethod("groups.getMembershipsLight", "GET", _R, _SEEN, _q("groupId", "portalRoles[]?")),
    AulaMethod("groups.joinOrLeaveGroup", "POST", _W, _WEB),
    AulaMethod("groups.setmembership", "POST", _W, _WEB),
    AulaMethod("groups.updateGroup", "POST", _W, _WEB),
    AulaMethod("groupsAdmin.deleteGroup", "POST", _W, _WEB),
    AulaMethod("groupsAdmin.getMemberships", "GET", _STAFF, _WEB),
    AulaMethod("GroupsAdmin.isInUse", "GET", _STAFF, _WEB),
    AulaMethod("GroupsAdmin.setAdminDeactivationForGroups", "POST", _W, _WEB),
    AulaMethod("identityProviders.getMunicipalIdPs", "GET", _STAFF, _WEB),
    AulaMethod("messaging.addRecipients", "POST", _W, _WEB),
    AulaMethod("messaging.attachMessagesToSecureDocument", "POST", _W, _WEB),
    AulaMethod("messaging.createFolder", "POST", _W, _WEB),
    AulaMethod("messaging.deleteAutoReply", "POST", _W, _WEB),
    AulaMethod("messaging.deleteFolder", "POST", _W, _WEB),
    AulaMethod("messaging.deleteMessage", "POST", _W, _WEB),
    AulaMethod("messaging.deleteThreads", "POST", _W, _WEB),
    AulaMethod("messaging.editMessage", "POST", _W, _WEB),
    AulaMethod("messaging.getAutoReply", "GET", _STAFF, _USED),
    AulaMethod("messaging.getCommonInboxes", "GET", _R, _USED, _q("institutionProfileIds[]")),
    AulaMethod("messaging.getFolders", "GET", _R, _SEEN, _q("IncludeDeletedFolders")),
    AulaMethod("messaging.getMessageInfoLight", "GET", _M, _USED, _q("ThreadId", "MessageId")),
    AulaMethod("messaging.getMessagesForThread", "GET", _M, _SEEN, _q("threadId", "page")),
    AulaMethod("messaging.getNewThreads", "GET", _M, _WEB),
    AulaMethod("messaging.getOtpInboxesForLoggedInProfile", "GET", _R, _WEB),
    AulaMethod("messaging.getThreads", "GET", _M, _SEEN, _q("sortOn", "orderDirection", "page")),
    AulaMethod("messaging.getThreadsInBundle", "GET", _M, _USED, _q("BundleId")),
    AulaMethod("messaging.leaveThread", "POST", _W, _WEB),
    AulaMethod("messaging.leaveThreads", "POST", _W, _WEB),
    AulaMethod("messaging.moveThreadsToFolder", "POST", _W, _WEB),
    AulaMethod("messaging.reply", "POST", _W, _WEB, (), _q("threadId", "message", "commonInboxId", "otpInboxId")),
    AulaMethod("messaging.sendEventReminder", "POST", _W, _WEB),
    AulaMethod("messaging.setAutoReply", "POST", _W, _WEB),
    AulaMethod("messaging.setLastReadMessage", "POST", _W, _USED, (), _q("threadId", "messageId", "commonInboxId", "otpInboxId")),
    AulaMethod("messaging.setSensitivityLevel", "POST", _W, _WEB),
    AulaMethod("messaging.setThreadsMarked", "POST", _W, _WEB),
    AulaMethod("messaging.setThreadsMuted", "POST", _W, _WEB),
    AulaMethod("messaging.startNewThread", "POST", _W, _WEB),
    AulaMethod("messaging.updateFolder", "POST", _W, _WEB),
    AulaMethod("messaging.updateSubscriptionStatus", "POST", _W, _WEB),
    AulaMethod("messagingAdmin.deleteThreads", "POST", _W, _WEB),
    AulaMethod("messagingAdmin.getMessageRevisions", "POST", _STAFF, _WEB),
    AulaMethod("messagingAdmin.getThreads", "GET", _STAFF, _WEB),
    AulaMethod("municipalConfiguration.getBlockedCommunicationInstitutionProfilesAndGroups", "POST", _STAFF, _WEB),
    AulaMethod("municipalConfiguration.getBlockedCommunicationProfiles", "GET", _STAFF, _WEB),
    AulaMethod("municipalConfiguration.getCalendarFeedEnabled", "GET", _STAFF, _WEB),
    AulaMethod("municipalConfiguration.getEditorPlugins", "GET", _STAFF, _WEB),
    AulaMethod("municipalConfiguration.getInstitutionsAndAdministrativeAuthorities", "GET", _STAFF, _WEB),
    AulaMethod("municipalConfiguration.getInstitutionsByAdministrativeAuthority", "GET", _STAFF, _WEB),
    AulaMethod("municipalConfiguration.getSameAdministrativeAuthorityInstitutions", "GET", _STAFF, _WEB),
    AulaMethod("municipalConfiguration.saveAdministrativeAuthority", "POST", _W, _WEB),
    AulaMethod("municipalConfiguration.updateCalendarFeedEnabled", "POST", _W, _WEB),
    AulaMethod("municipalConfiguration.updateEditorPluginConfigurations", "POST", _W, _WEB),
    AulaMethod("municipalConfigurationAdmin.getRightToBeForgottenRequests", "GET", _STAFF, _WEB),
    AulaMethod("municipalConfigurationAdmin.handleEntities", "POST", _W, _WEB),
    AulaMethod("NoticeBoardDevice.getCalendarEvent", "GET", _STAFF, _WEB),
    AulaMethod("NoticeBoardDevice.getCalendarEvents", "GET", _STAFF, _WEB),
    AulaMethod("NoticeBoardDevice.getMedia", "GET", _STAFF, _WEB),
    AulaMethod("NoticeBoardDevice.getPosts", "GET", _STAFF, _WEB),
    AulaMethod("notifications.deleteBadgeNotificationByModule", "POST", _W, _WEB),
    AulaMethod("Notifications.deleteNotifications", "POST", _W, _WEB),
    AulaMethod("Notifications.getNotificationSettingsForActiveProfile", "GET", _R, _SEEN),
    AulaMethod("notifications.getNotificationsForActiveProfile", "GET", _R, _SEEN, _q("activeChildrenIds[]", "activeInstitutionCodes[]")),
    AulaMethod("notifications.isUnsubscribeTokenValid", "GET", _T, _WEB),
    AulaMethod("Notifications.setNotificationSettingsForActiveProfile", "POST", _W, _WEB),
    AulaMethod("notifications.unregisterAllDevices", "POST", _W, _WEB),
    AulaMethod("notifications.unsubscribeNotifications", "POST", _W, _WEB),
    AulaMethod("personalReferenceData.getPersonalReferenceDataAdditionalDataAnswer", "GET", _P, _WEB),
    AulaMethod("personalReferenceData.getPersonalReferenceDataConsentAnswer", "GET", _P, _WEB),
    AulaMethod("personalReferenceData.getPersonalReferenceDataQuestion", "GET", _P, _WEB),
    AulaMethod("posts.acceptReportedPost", "POST", _W, _WEB),
    AulaMethod("posts.bookmark", "POST", _W, _WEB),
    AulaMethod("posts.createPost", "POST", _W, _WEB),
    AulaMethod("posts.deletePost", "POST", _W, _WEB),
    AulaMethod("posts.getAllPosts", "GET", _R, _SEEN, _q("parent", "index", "limit", "institutionProfileIds[]")),
    AulaMethod("posts.getAllPostsForAdmin", "GET", _STAFF, _WEB),
    AulaMethod("posts.getById", "GET", _R, _SEEN, _q("id")),
    AulaMethod("posts.getPostForGroupAdminById", "GET", _STAFF, _WEB),
    AulaMethod("posts.getReportedPosts", "POST", _STAFF, _WEB),
    AulaMethod("posts.rejectReportedPost", "POST", _W, _WEB),
    AulaMethod("posts.reportPost", "POST", _W, _WEB),
    AulaMethod("posts.unbookmark", "POST", _W, _WEB),
    AulaMethod("posts.updatePost", "POST", _W, _WEB),
    AulaMethod("postsAdmin.deletePost", "POST", _W, _WEB),
    AulaMethod("postsAdmin.getAllPostsForCreator", "GET", _STAFF, _WEB),
    AulaMethod("presence.addSleepIntervals", "POST", _W, _WEB),
    AulaMethod("presence.bulkUpdatePresenceStatus", "POST", _W, _WEB),
    AulaMethod("presence.deletePickupResponsible", "POST", _W, _WEB),
    AulaMethod("presence.deleteRepeatingPresenceTemplate", "POST", _W, _WEB),
    AulaMethod("presence.deleteSleepIntervals", "POST", _W, _WEB),
    AulaMethod("presence.getActivityList", "POST", _STAFF, _WEB),
    AulaMethod("presence.getActivityOverview", "GET", _STAFF, _USED, _q("institutionProfileIds[]", "week", "year")),
    AulaMethod("presence.getClosedDays", "GET", _R, _WEB, _q("institutionCodes[]")),
    AulaMethod("presence.getDailyOverview", "GET", _R, _SEEN, _q("childIds[]")),
    AulaMethod("presence.getGeneralOpeningHours", "GET", _R, _WEB, _q("institutionCodes[]")),
    AulaMethod("presence.getGoHomeWithList", "GET", _STAFF, _WEB),
    AulaMethod("presence.getOpeningHoursByInstitutionCodes", "GET", _R, _WEB, _q("institutionCodes[]", "startDate", "endDate")),
    AulaMethod("presence.getOverlappingPresenceTemplates", "GET", _R, _WEB),
    AulaMethod("presence.getPickupResponsibles", "GET", _R, _SEEN, _q("uniStudentIds[]")),
    AulaMethod("presence.getPresenceConfiguration", "GET", _STAFF, _WEB),
    AulaMethod("presence.getPresenceConfigurationByChildIds", "GET", _R, _SEEN, _q("childIds[]")),
    AulaMethod("presence.getPresenceDistribution", "GET", _STAFF, _WEB),
    AulaMethod("presence.getPresenceFilters", "GET", _STAFF, _WEB),
    AulaMethod("presence.getPresenceRegistrationDetail", "GET", _STAFF, _USED, _q("id")),
    AulaMethod("presence.getPresenceRegistrations", "GET", _STAFF, _USED, _q("institutionProfileIds[]", "fromDate", "toDate")),
    AulaMethod("presence.getPresenceStates", "GET", _R, _SEEN, _q("institutionProfileIds[]?")),
    AulaMethod("presence.getPresenceTemplates", "GET", _R, _SEEN, _q("filterInstitutionProfileIds[]", "fromDate", "toDate")),
    AulaMethod("presence.getSpecificOpeningHourOverview", "GET", _R, _WEB, _q("institutionCodes[]")),
    AulaMethod("presence.getSuggestedNamesForPickupChild", "GET", _STAFF, _WEB),
    AulaMethod("presence.getTemplateForDate", "GET", _R, _WEB),
    AulaMethod("presence.getVacationAnnouncementsByChildren", "GET", _R, _SEEN, _q("childIds[]")),
    AulaMethod("presence.getVacationRegistrationResponse", "GET", _R, _SEEN, _q("vacationRegistrationResponseId")),
    AulaMethod("presence.getVacationRegistrations", "GET", _STAFF, _WEB),
    AulaMethod("presence.getVacationRegistrationsByChildren", "GET", _R, _SEEN, _q("childIds[]")),
    AulaMethod("presence.savePickupNames", "POST", _W, _WEB),
    AulaMethod("presence.updateCheckoutActivity", "POST", _W, _WEB),
    AulaMethod("presence.updateLocation", "POST", _W, _WEB),
    AulaMethod("presence.updatePresenceRegistration", "POST", _W, _WEB),
    AulaMethod("presence.updatePresenceTemplate", "POST", _W, _USED, (), _q("institutionProfileId", "byDate", "presenceActivity", "comment", "repeatPattern", "expiresAt", "id?")),
    AulaMethod("presence.updateSleepInterval", "POST", _W, _WEB),
    AulaMethod("presence.updateStatusByInstitutionProfileIds", "POST", _W, _USED, (), _q("institutionProfileIds", "status")),
    AulaMethod("presenceAdmin.deleteAllPickUpNames", "POST", _W, _WEB),
    AulaMethod("profiles.endImpersonation", "GET", _W, _WEB),
    AulaMethod("profiles.getAdditionalDataResponsesByInstitutionProfileIds", "GET", _P, _WEB),
    AulaMethod("profiles.getAdditionalDataResponsesForOwner", "GET", _P, _WEB),
    AulaMethod("profiles.getAnyUnansweredAdditionalDataResponsesForOwner", "GET", _P, _WEB),
    AulaMethod("profiles.getContactlist", "GET", _R, _SEEN, _q("groupId", "filter", "field", "page", "order")),
    AulaMethod("profiles.getContactParents", "GET", _STAFF, _USED, _q("page", "order")),
    AulaMethod("profiles.getProfileByProfileCtx", "GET", _R, _WEB),
    AulaMethod("profiles.getProfileContext", "GET", _R, _SEEN, _q("portalrole")),
    AulaMethod("profiles.getProfileMasterData", "GET", _R, _SEEN, _q("instProfileIds[]", "fromAdministration")),
    AulaMethod("profiles.getProfilesByLogin", "GET", _R, _SEEN),
    AulaMethod("profiles.impersonateUser", "GET", _W, _WEB),
    AulaMethod("profiles.keepAlive", "GET", _W, _USED),
    AulaMethod("profiles.markOnboardingCompleted", "GET", _W, _WEB),
    AulaMethod("profiles.updateAdditionalDataResponses", "POST", _W, _WEB),
    AulaMethod("profiles.updateAdditionalDataResponsesEmployee", "POST", _W, _WEB),
    AulaMethod("profiles.updateProfileMasterData", "POST", _W, _WEB),
    AulaMethod("profiles.updateProfilePicture", "POST", _W, _WEB),
    AulaMethod("profilesAdmin.deleteAdditionalDataResponsesByInstitutionProfileIds", "POST", _W, _WEB),
    AulaMethod("profilesAdmin.deleteProfileMasterData", "POST", _W, _WEB),
    AulaMethod("profilesAdmin.getAdditionalDataResponseRevisionHistory", "GET", _STAFF, _WEB),
    AulaMethod("profilesAdmin.getAdditionalDataResponsesForOwner", "GET", _STAFF, _WEB),
    AulaMethod("profilesAdmin.getLockHistory", "GET", _STAFF, _WEB),
    AulaMethod("profilesAdmin.getUserData", "GET", _STAFF, _WEB),
    AulaMethod("resources.listAvailableResources", "GET", _STAFF, _WEB),
    AulaMethod("resources.listResources", "GET", _STAFF, _WEB),
    AulaMethod("roleAdministration.listassignedgrouproles", "GET", _W, _WEB),
    AulaMethod("roleAdministration.listassignedrolesforgroups", "POST", _W, _WEB),
    AulaMethod("roleAdministration.listroledefinitions", "GET", _W, _WEB),
    AulaMethod("search.findGeneric", "GET", _M, _USED, _q("Text", "Limit", "Offset", "DocTypeCount", "DocType?")),
    AulaMethod("search.findGroups", "GET", _R, _USED, _q("text", "limit")),
    AulaMethod("search.findMessage", "POST", _M, _USED, (), _q("text", "typeahead", "exactTerm", "activeChildrenInstitutionProfileIds", "institutionCodes", "limit", "offset", "commonInboxID", "filterBy", "sortBy", "sortDirection", "threadSubject", "messageContent", "fromDate", "toDate", "threadCreators", "participants", "hasAttachments")),
    AulaMethod("search.findProfilesAndGroups", "GET", _R, _USED, _q("Text", "Limit", "Typeahead")),
    AulaMethod("search.findRecipients", "GET", _R, _USED, _q("Text", "Limit", "TypeAhead", "DocTypes?", "PortalRoles?")),
    AulaMethod("session.keepAlive", "GET", _W, _WEB),
    AulaMethod("session.stepUpCurrentSession", "POST", _W, _WEB),
)

METHODS: Mapping[str, AulaMethod] = {method.name: method for method in _ALL}
"""Every method known to exist, by its name as Aula spells it."""


_BY_LOWER = {name.lower(): method for name, method in METHODS.items()}


def known(name: str) -> AulaMethod | None:
    """The method known by `name`, spelt as Aula spells it; None where none is."""
    return METHODS.get(name)


def alike(name: str) -> AulaMethod | None:
    """The method known by `name` in any case; None where none is."""
    return _BY_LOWER.get(name.lower())

