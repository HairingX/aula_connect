# The methods of Aula's API

Aula's API is one address, `https://www.aula.dk/api/v<version>`, asked with the method's name in
`method=` and its parameters beside it. `aula_connect.methods` lists every method known to exist,
and how it is asked, so that none is guessed. `AulaClient.read` asks a listed method with its verb,
and never one of a kind it does not ask, whatever the case of its name.

- **Spelling.** Aula tells names apart by their case: `profiles.getContactList` is no method, where
  `profiles.getContactlist` is. A name is listed as Aula spells it. The parameters' spelling
  varies from method to method too, such as `Start` against `start`; each is listed as asked.
- **Verb.** Most methods are asked with GET. A few that only read are asked with POST and a JSON
  body, such as `calendar.getEventsByProfileIdsAndResourceIds`.
- **Kind.** `read` only gets. `messages` gets the text of messages and `secure_documents` secure
  documents, either of which may be marked sensitive; `token` hands out a token, a credential;
  `write` changes Aula, as some that are asked with GET do, such as
  `profiles.markOnboardingCompleted`; `personal` gets a person's answers to Aula's questions, which
  may be sensitive; `staff` gets what only the institution's staff, administrators or devices see,
  which Aula refuses a guardian or asks only in its staff's views. Only `read` is ever asked by
  `read`.
- **Evidence.** `seen`: Aula answered it, as listed, in this library's own reads. `used`: a
  maintained client of Aula's API asks it, as listed; `web`: Aula's own web app asks it; neither
  is seen answered here.
- **Errors.** Aula answers a name it has no method by with code 10, and parameters it does not
  take with HTTP 400 and code 40.

`AulaClient.read_everything` asks every listed method that only reads once, about the account's
own children, institutions and main groups, with the values the maintained client sends, and
then the first items of a list one by one, such as a post by its id; a method it cannot ask, as
it searches for a text, it names with why.

A name not listed may still be one Aula has. `read` asks one where it is named as a method that
gets, `<area>.get<What>` or `<area>.find<What>`, and is about neither messages nor secure documents.

The methods marked `used` and their parameters are as a maintained client of Aula's API asks
them. Where Aula's own web app spells one otherwise, it is listed as Aula spells it: `Documents.getSecureDocuments` and
`Notifications.getNotificationSettingsForActiveProfile`.

## Aula's own web app

Aula's own web app is the last word on what a method is called and how it is asked: its page,
https://www.aula.dk/portal/, loads its scripts from `/static/js/`, public and with no login, and
each asks a method as `.get("?method=<name>"` or `.post("?method=<name>"`.
`python scripts/aula_web_methods.py [FILE.json]` fetches them and prints what the catalog says
otherwise - a name spelt otherwise, a verb otherwise, a method the web app does not ask, and one
it asks that the catalog lacks - and writes every method it asks, with its verbs, to the file
where given. Their parameters are read in the scripts at each place a method is asked. A method
the web app does not ask may still be the mobile app's.

<!-- The table below is checked against aula_connect.methods by the tests. -->

## Methods

| Method | Verb | Kind | Evidence | Query | Body |
|---|---|---|---|---|---|
| `aulaToken.getAulaToken` | GET | token | seen | `widgetId` | - |
| `calendar.addVacation` | POST | write | used | - | `childIds`, `intervals`, `comment` |
| `calendar.blockTimeSlot` | POST | write | web | - | - |
| `calendar.checkConflictEventForAttendees` | POST | write | web | - | - |
| `calendar.createRepeatingEvent` | POST | write | web | - | - |
| `calendar.createSimpleEvent` | POST | write | web | - | - |
| `calendar.createTimeSlotEvent` | POST | write | web | - | - |
| `calendar.createVacationRequest` | POST | write | web | - | - |
| `calendar.deleteEvent` | POST | write | web | - | `id` |
| `calendar.getBirthdayEventsForGroup` | GET | read | seen | `groupId`, `start`, `end` | - |
| `calendar.getBirthdayEventsForInstitutions` | GET | read | seen | `instCodes[]`, `start`, `end` | - |
| `calendar.getDailyAggregatedEvents` | GET | read | seen | `InstProfileIds[]`, `Start`, `End` | - |
| `calendar.getDailyEventCountForGroup` | GET | read | seen | `GroupId`, `Start`, `End` | - |
| `calendar.getDelegatedAccesses` | GET | staff | web | - | - |
| `calendar.getDelegatedContext` | GET | staff | web | - | - |
| `calendar.getEventById` | GET | read | used | `eventId`, `occurrenceDateTime` (optional) | - |
| `calendar.getEventsByGroupHomeChildPairs` | POST | read | web | - | - |
| `calendar.geteventsbygroupid` | GET | read | seen | `groupId`, `start`, `end` | - |
| `calendar.getEventsByProfileIdsAndResourceIds` | POST | read | seen | - | `instProfileIds`, `resourceIds`, `start`, `end` |
| `calendar.getEventsForInstitutions` | GET | staff | used | `Start`, `End`, `InstCodes[]` | - |
| `calendar.getEventTypes` | GET | read | seen | `Type`, `FilterInstitutionCodes[]` (optional) | - |
| `calendar.getFutureVacationRequests` | GET | read | web | - | - |
| `calendar.getGuardiansWithPendingVacationRequestResponses` | GET | staff | web | - | - |
| `calendar.getImportantDates` | GET | read | seen | `limit`, `includeToday` | - |
| `calendar.getInstitutionProfilesWithDelegatedAccess` | GET | staff | web | - | - |
| `calendar.getTimeSlotResponse` | GET | read | web | - | - |
| `calendar.getVacationRequestResponses` | GET | staff | web | - | - |
| `calendar.removeAttendeeFromEvent` | POST | write | web | - | - |
| `calendar.removeBlockingOrResponseToTimeSlot` | POST | write | web | - | - |
| `calendar.requestVacation` | POST | write | web | - | - |
| `calendar.respondToEvent` | POST | write | web | - | - |
| `calendar.respondToSimpleEvent` | POST | write | web | - | - |
| `calendar.respondToTimeSlotEvent` | POST | write | web | - | - |
| `calendar.respondToVacationRegistrationRequest` | POST | write | web | - | `vacationRegistrationResponseId`, `childId`, `days`, `comment` |
| `calendar.setDelegatedAccesses` | POST | write | web | - | - |
| `calendar.setDelegatedContext` | POST | write | web | - | - |
| `calendar.updateEventResources` | POST | write | web | - | - |
| `calendar.updateLessonEvent` | POST | write | web | - | - |
| `calendar.updateRepeatingEvent` | POST | write | web | - | - |
| `calendar.updateResponseToTimeSlotEvent` | POST | write | web | - | - |
| `calendar.updateSimpleEvent` | POST | write | web | - | - |
| `calendar.updateTimeSlotEvent` | POST | write | web | - | - |
| `calendar.updateVacationRequest` | POST | write | web | - | - |
| `calendarAdmin.deleteEvent` | POST | write | web | - | - |
| `calendarAdmin.getEventsByProfileId` | GET | staff | web | - | - |
| `CalendarFeed.createFeedConfiguration` | POST | write | web | - | - |
| `calendarFeed.getEventTypesRelevantForPortalRole` | GET | read | web | - | - |
| `CalendarFeed.getFeedConfigurations` | GET | read | web | - | - |
| `CalendarFeed.getPolicyAnswer` | GET | read | web | - | - |
| `CalendarFeed.removeFeedConfiguration` | POST | write | web | - | - |
| `CalendarFeed.setPolicyAnswer` | POST | write | web | - | - |
| `CalendarFeed.updateFeedConfiguration` | POST | write | web | - | - |
| `centralConfiguration.createAuthorizedFileFormat` | POST | write | web | - | - |
| `centralConfiguration.getAuthorizedFileFormats` | GET | staff | web | - | - |
| `CentralConfiguration.getDataPolicy` | GET | read | web | - | - |
| `centralConfiguration.getLoginImportantInformation` | GET | read | web | - | - |
| `centralConfiguration.getMaxFileSize` | GET | staff | web | - | - |
| `CentralConfiguration.getOpenDataPolicy` | GET | read | web | - | - |
| `centralConfiguration.removeAuthorizedFileFormat` | POST | write | web | - | - |
| `centralConfiguration.setMaxFileSize` | POST | write | web | - | - |
| `comments.acceptReport` | POST | write | web | - | - |
| `comments.addComment` | POST | write | web | - | - |
| `comments.deleteComment` | POST | write | web | - | - |
| `comments.getComments` | GET | read | used | `parentType`, `parentId`, `startIndex`, `limit` | - |
| `comments.getReportedComments` | POST | staff | web | - | - |
| `comments.rejectReport` | POST | write | web | - | - |
| `comments.reportComment` | POST | write | web | - | - |
| `comments.updateComment` | POST | write | web | - | - |
| `commentsAdmin.getAllCommentsForUser` | GET | staff | web | - | - |
| `commentsAdmin.hardDeleteComment` | POST | write | web | - | - |
| `commonFiles.getCommonFiles` | GET | read | seen | `index`, `limit`, `institutionCodes[]` | - |
| `commonFiles.getPersonalDataPolicies` | GET | read | web | - | - |
| `commonFilesAdmin.createCommonFile` | POST | write | web | - | - |
| `commonFilesAdmin.deleteCommonFile` | POST | write | web | - | - |
| `commonFilesAdmin.getCommonFileById` | GET | staff | web | - | - |
| `commonFilesAdmin.getInstitutionDataPolicyName` | GET | staff | web | - | - |
| `commonFilesAdmin.titleExistsOnInstitution` | GET | write | web | - | - |
| `commonFilesAdmin.updateCommonFile` | POST | write | web | - | - |
| `consents.getConsentResponses` | GET | read | seen | `institutionProfileIds[]` | - |
| `consents.updateConsentResponses` | POST | write | web | - | - |
| `consentsAdmin.deleteConsentResponseAnswersByInstitutionProfileId` | POST | write | web | - | - |
| `consentsAdmin.getConsentResponseRevisionHistory` | GET | staff | web | - | - |
| `dashboards.getAdminDashboardConfiguration` | GET | staff | web | - | - |
| `dashboards.getWidgetsByIds` | GET | staff | web | - | - |
| `dashboardsAdmin.getAllModules` | GET | staff | web | - | - |
| `dashboardsAdmin.getAllWidgets` | GET | staff | web | - | - |
| `documents.createArchiveForMultipleSecureDocuments` | POST | write | web | - | - |
| `documents.createExternalSecureFile` | POST | write | web | - | - |
| `documents.createInternalSecureDocument` | POST | write | web | - | - |
| `documents.deleteDocument` | POST | write | web | - | - |
| `documents.exportDocumentsToEsdh` | POST | write | web | - | - |
| `Documents.getDocumentCategoriesAndTemplates` | GET | secure_documents | web | - | - |
| `Documents.getDocumentRevision` | GET | secure_documents | web | - | - |
| `Documents.getDocumentRevisions` | GET | secure_documents | web | - | - |
| `documents.getExternalSecureFile` | GET | secure_documents | web | - | - |
| `Documents.getImplicitSharings` | POST | secure_documents | web | - | - |
| `documents.getInternalSecureDocument` | GET | secure_documents | web | - | - |
| `documents.getMaxDocumentsPerExport` | GET | secure_documents | web | - | - |
| `Documents.getSecureDocuments` | POST | secure_documents | used | - | `index`, `limit`, `filterInstitutionProfileIds` |
| `Documents.getShareableSecureDocuments` | POST | secure_documents | web | - | - |
| `documents.markAsRead` | POST | write | web | - | - |
| `documents.markAsUnread` | POST | write | web | - | - |
| `documents.removeOwnSharings` | POST | write | web | - | - |
| `documents.trackCreateArchiveForMultipleSecureDocumentsRequest` | POST | write | web | - | - |
| `documents.updateExternalSecureFile` | POST | write | web | - | - |
| `documents.updateInternalSecureDocument` | POST | write | web | - | - |
| `documents.updateLockedStatus` | POST | write | web | - | - |
| `documents.updateSharings` | POST | write | web | - | - |
| `documentsAdmin.deleteDocuments` | POST | write | web | - | - |
| `documentsAdmin.getDeletedSecureDocuments` | POST | staff | web | - | - |
| `documentsAdmin.getSecureDocumentsRegardingInstitutionProfile` | GET | staff | web | - | - |
| `documentsAdmin.restoreDeletedDocument` | POST | write | web | - | - |
| `EsdhDataExportAdmin.addEsdhDataExportRecipient` | POST | write | web | - | - |
| `EsdhDataExportAdmin.deleteEsdhDataExportRecipient` | POST | write | web | - | - |
| `EsdhDataExportAdmin.getEsdhDataExportConfiguration` | GET | staff | web | - | - |
| `EsdhDataExportAdmin.getExportData` | GET | staff | web | - | - |
| `EsdhDataExportAdmin.getExportDataForMunicipality` | GET | staff | web | - | - |
| `EsdhDataExportAdmin.getRecipientNames` | GET | staff | web | - | - |
| `EsdhDataExportAdmin.journalizeDocuments` | POST | write | web | - | - |
| `EsdhDataExportAdmin.markDocumentsForManualTransfer` | POST | write | web | - | - |
| `EsdhDataExportAdmin.resendDocuments` | POST | write | web | - | - |
| `EsdhDataExportAdmin.updateEsdhDataExportRecipient` | POST | write | web | - | - |
| `files.completeMultipartUploading` | POST | write | web | - | - |
| `files.createAttachments` | POST | write | web | - | - |
| `files.createDocumentLinks` | POST | write | web | - | - |
| `files.updateAttachments` | POST | write | web | - | - |
| `gallery.acceptReportedMedia` | POST | write | web | - | - |
| `gallery.createAlbum` | POST | write | web | - | - |
| `gallery.createMedia` | POST | write | web | - | - |
| `gallery.deleteAlbums` | POST | write | web | - | - |
| `gallery.deleteMedia` | POST | write | web | - | - |
| `gallery.getAlbums` | GET | read | seen | `index`, `limit`, `sortOn`, `orderDirection`, `filterBy`, `filterInstProfileIds[]` | - |
| `gallery.getMedia` | GET | read | seen | `albumId`, `index`, `limit`, `sortOn`, `orderDirection`, `filterBy`, `filterInstProfileIds[]` | - |
| `gallery.getMediaById` | GET | read | seen | `id` | - |
| `gallery.getReportedMedia` | POST | staff | web | - | - |
| `gallery.rejectReportedMedia` | POST | write | web | - | - |
| `gallery.reportMedia` | POST | write | web | - | - |
| `gallery.updateAlbum` | POST | write | web | - | - |
| `gallery.updateMedia` | POST | write | web | - | - |
| `galleryAdmin.deleteMedia` | POST | write | web | - | - |
| `galleryAdmin.getAlbums` | GET | staff | web | - | - |
| `galleryAdmin.getMedia` | GET | staff | web | - | - |
| `galleryAdmin.getMediaByInstitutionProfileId` | GET | staff | web | - | - |
| `genericAdmin.getInstitutions` | GET | staff | web | - | - |
| `genericAdmin.getMunicipalities` | GET | staff | web | - | - |
| `groups.createGroup` | POST | write | web | - | - |
| `groups.deleteGroupMemberships` | POST | write | web | - | - |
| `groups.getDirectMemberships` | GET | staff | web | - | - |
| `groups.getGroupById` | GET | read | seen | `groupId` | - |
| `groups.getGroupsByContext` | GET | read | seen | `childInstitutionProfileIds[]` (optional), `institutionCodes[]` (optional) | - |
| `groups.getMemberships` | GET | read | web | `groupId`, `portalRoles[]` (optional) | - |
| `groups.getMembershipsLight` | GET | read | seen | `groupId`, `portalRoles[]` (optional) | - |
| `groups.joinOrLeaveGroup` | POST | write | web | - | - |
| `groups.setmembership` | POST | write | web | - | - |
| `groups.updateGroup` | POST | write | web | - | - |
| `groupsAdmin.deleteGroup` | POST | write | web | - | - |
| `groupsAdmin.getMemberships` | GET | staff | web | - | - |
| `GroupsAdmin.isInUse` | GET | staff | web | - | - |
| `GroupsAdmin.setAdminDeactivationForGroups` | POST | write | web | - | - |
| `identityProviders.getMunicipalIdPs` | GET | staff | web | - | - |
| `messaging.addRecipients` | POST | write | web | - | - |
| `messaging.attachMessagesToSecureDocument` | POST | write | web | - | - |
| `messaging.createFolder` | POST | write | web | - | - |
| `messaging.deleteAutoReply` | POST | write | web | - | - |
| `messaging.deleteFolder` | POST | write | web | - | - |
| `messaging.deleteMessage` | POST | write | web | - | - |
| `messaging.deleteThreads` | POST | write | web | - | - |
| `messaging.editMessage` | POST | write | web | - | - |
| `messaging.getAutoReply` | GET | staff | used | - | - |
| `messaging.getCommonInboxes` | GET | read | used | `institutionProfileIds[]` | - |
| `messaging.getFolders` | GET | read | seen | `IncludeDeletedFolders` | - |
| `messaging.getMessageInfoLight` | GET | messages | used | `ThreadId`, `MessageId` | - |
| `messaging.getMessagesForThread` | GET | messages | seen | `threadId`, `page` | - |
| `messaging.getNewThreads` | GET | messages | web | - | - |
| `messaging.getOtpInboxesForLoggedInProfile` | GET | read | web | - | - |
| `messaging.getThreads` | GET | messages | seen | `sortOn`, `orderDirection`, `page` | - |
| `messaging.getThreadsInBundle` | GET | messages | used | `BundleId` | - |
| `messaging.leaveThread` | POST | write | web | - | - |
| `messaging.leaveThreads` | POST | write | web | - | - |
| `messaging.moveThreadsToFolder` | POST | write | web | - | - |
| `messaging.reply` | POST | write | web | - | `threadId`, `message`, `commonInboxId`, `otpInboxId` |
| `messaging.sendEventReminder` | POST | write | web | - | - |
| `messaging.setAutoReply` | POST | write | web | - | - |
| `messaging.setLastReadMessage` | POST | write | used | - | `threadId`, `messageId`, `commonInboxId`, `otpInboxId` |
| `messaging.setSensitivityLevel` | POST | write | web | - | - |
| `messaging.setThreadsMarked` | POST | write | web | - | - |
| `messaging.setThreadsMuted` | POST | write | web | - | - |
| `messaging.startNewThread` | POST | write | web | - | - |
| `messaging.updateFolder` | POST | write | web | - | - |
| `messaging.updateSubscriptionStatus` | POST | write | web | - | - |
| `messagingAdmin.deleteThreads` | POST | write | web | - | - |
| `messagingAdmin.getMessageRevisions` | POST | staff | web | - | - |
| `messagingAdmin.getThreads` | GET | staff | web | - | - |
| `municipalConfiguration.getBlockedCommunicationInstitutionProfilesAndGroups` | POST | staff | web | - | - |
| `municipalConfiguration.getBlockedCommunicationProfiles` | GET | staff | web | - | - |
| `municipalConfiguration.getCalendarFeedEnabled` | GET | staff | web | - | - |
| `municipalConfiguration.getEditorPlugins` | GET | staff | web | - | - |
| `municipalConfiguration.getInstitutionsAndAdministrativeAuthorities` | GET | staff | web | - | - |
| `municipalConfiguration.getInstitutionsByAdministrativeAuthority` | GET | staff | web | - | - |
| `municipalConfiguration.getSameAdministrativeAuthorityInstitutions` | GET | staff | web | - | - |
| `municipalConfiguration.saveAdministrativeAuthority` | POST | write | web | - | - |
| `municipalConfiguration.updateCalendarFeedEnabled` | POST | write | web | - | - |
| `municipalConfiguration.updateEditorPluginConfigurations` | POST | write | web | - | - |
| `municipalConfigurationAdmin.getRightToBeForgottenRequests` | GET | staff | web | - | - |
| `municipalConfigurationAdmin.handleEntities` | POST | write | web | - | - |
| `NoticeBoardDevice.getCalendarEvent` | GET | staff | web | - | - |
| `NoticeBoardDevice.getCalendarEvents` | GET | staff | web | - | - |
| `NoticeBoardDevice.getMedia` | GET | staff | web | - | - |
| `NoticeBoardDevice.getPosts` | GET | staff | web | - | - |
| `notifications.deleteBadgeNotificationByModule` | POST | write | web | - | - |
| `Notifications.deleteNotifications` | POST | write | web | - | - |
| `Notifications.getNotificationSettingsForActiveProfile` | GET | read | seen | - | - |
| `notifications.getNotificationsForActiveProfile` | GET | read | seen | `activeChildrenIds[]`, `activeInstitutionCodes[]` | - |
| `notifications.isUnsubscribeTokenValid` | GET | token | web | - | - |
| `Notifications.setNotificationSettingsForActiveProfile` | POST | write | web | - | - |
| `notifications.unregisterAllDevices` | POST | write | web | - | - |
| `notifications.unsubscribeNotifications` | POST | write | web | - | - |
| `personalReferenceData.getPersonalReferenceDataAdditionalDataAnswer` | GET | personal | web | - | - |
| `personalReferenceData.getPersonalReferenceDataConsentAnswer` | GET | personal | web | - | - |
| `personalReferenceData.getPersonalReferenceDataQuestion` | GET | personal | web | - | - |
| `posts.acceptReportedPost` | POST | write | web | - | - |
| `posts.bookmark` | POST | write | web | - | - |
| `posts.createPost` | POST | write | web | - | - |
| `posts.deletePost` | POST | write | web | - | - |
| `posts.getAllPosts` | GET | read | seen | `parent`, `index`, `limit`, `institutionProfileIds[]` | - |
| `posts.getAllPostsForAdmin` | GET | staff | web | - | - |
| `posts.getById` | GET | read | seen | `id` | - |
| `posts.getPostForGroupAdminById` | GET | staff | web | - | - |
| `posts.getReportedPosts` | POST | staff | web | - | - |
| `posts.rejectReportedPost` | POST | write | web | - | - |
| `posts.reportPost` | POST | write | web | - | - |
| `posts.unbookmark` | POST | write | web | - | - |
| `posts.updatePost` | POST | write | web | - | - |
| `postsAdmin.deletePost` | POST | write | web | - | - |
| `postsAdmin.getAllPostsForCreator` | GET | staff | web | - | - |
| `presence.addSleepIntervals` | POST | write | web | - | - |
| `presence.bulkUpdatePresenceStatus` | POST | write | web | - | - |
| `presence.deletePickupResponsible` | POST | write | web | - | - |
| `presence.deleteRepeatingPresenceTemplate` | POST | write | web | - | - |
| `presence.deleteSleepIntervals` | POST | write | web | - | - |
| `presence.getActivityList` | POST | staff | web | - | - |
| `presence.getActivityOverview` | GET | staff | used | `institutionProfileIds[]`, `week`, `year` | - |
| `presence.getClosedDays` | GET | read | web | `institutionCodes[]` | - |
| `presence.getDailyOverview` | GET | read | seen | `childIds[]` | - |
| `presence.getGeneralOpeningHours` | GET | read | web | `institutionCodes[]` | - |
| `presence.getGoHomeWithList` | GET | staff | web | - | - |
| `presence.getOpeningHoursByInstitutionCodes` | GET | read | web | `institutionCodes[]`, `startDate`, `endDate` | - |
| `presence.getOverlappingPresenceTemplates` | GET | read | web | - | - |
| `presence.getPickupResponsibles` | GET | read | seen | `uniStudentIds[]` | - |
| `presence.getPresenceConfiguration` | GET | staff | web | - | - |
| `presence.getPresenceConfigurationByChildIds` | GET | read | seen | `childIds[]` | - |
| `presence.getPresenceDistribution` | GET | staff | web | - | - |
| `presence.getPresenceFilters` | GET | staff | web | - | - |
| `presence.getPresenceRegistrationDetail` | GET | staff | used | `id` | - |
| `presence.getPresenceRegistrations` | GET | staff | used | `institutionProfileIds[]`, `fromDate`, `toDate` | - |
| `presence.getPresenceStates` | GET | read | seen | `institutionProfileIds[]` (optional) | - |
| `presence.getPresenceTemplates` | GET | read | seen | `filterInstitutionProfileIds[]`, `fromDate`, `toDate` | - |
| `presence.getSpecificOpeningHourOverview` | GET | read | web | `institutionCodes[]` | - |
| `presence.getSuggestedNamesForPickupChild` | GET | staff | web | - | - |
| `presence.getTemplateForDate` | GET | read | web | - | - |
| `presence.getVacationAnnouncementsByChildren` | GET | read | seen | `childIds[]` | - |
| `presence.getVacationRegistrationResponse` | GET | read | seen | `vacationRegistrationResponseId` | - |
| `presence.getVacationRegistrations` | GET | staff | web | - | - |
| `presence.getVacationRegistrationsByChildren` | GET | read | seen | `childIds[]` | - |
| `presence.savePickupNames` | POST | write | web | - | - |
| `presence.updateCheckoutActivity` | POST | write | web | - | - |
| `presence.updateLocation` | POST | write | web | - | - |
| `presence.updatePresenceRegistration` | POST | write | web | - | - |
| `presence.updatePresenceTemplate` | POST | write | used | - | `institutionProfileId`, `byDate`, `presenceActivity`, `comment`, `repeatPattern`, `expiresAt`, `id` (optional) |
| `presence.updateSleepInterval` | POST | write | web | - | - |
| `presence.updateStatusByInstitutionProfileIds` | POST | write | used | - | `institutionProfileIds`, `status` |
| `presenceAdmin.deleteAllPickUpNames` | POST | write | web | - | - |
| `profiles.endImpersonation` | GET | write | web | - | - |
| `profiles.getAdditionalDataResponsesByInstitutionProfileIds` | GET | personal | web | - | - |
| `profiles.getAdditionalDataResponsesForOwner` | GET | personal | web | - | - |
| `profiles.getAnyUnansweredAdditionalDataResponsesForOwner` | GET | personal | web | - | - |
| `profiles.getContactlist` | GET | read | seen | `groupId`, `filter`, `field`, `page`, `order` | - |
| `profiles.getContactParents` | GET | staff | used | `page`, `order` | - |
| `profiles.getProfileByProfileCtx` | GET | read | web | - | - |
| `profiles.getProfileContext` | GET | read | seen | `portalrole` | - |
| `profiles.getProfileMasterData` | GET | read | seen | `instProfileIds[]`, `fromAdministration` | - |
| `profiles.getProfilesByLogin` | GET | read | seen | - | - |
| `profiles.impersonateUser` | GET | write | web | - | - |
| `profiles.keepAlive` | GET | write | used | - | - |
| `profiles.markOnboardingCompleted` | GET | write | web | - | - |
| `profiles.updateAdditionalDataResponses` | POST | write | web | - | - |
| `profiles.updateAdditionalDataResponsesEmployee` | POST | write | web | - | - |
| `profiles.updateProfileMasterData` | POST | write | web | - | - |
| `profiles.updateProfilePicture` | POST | write | web | - | - |
| `profilesAdmin.deleteAdditionalDataResponsesByInstitutionProfileIds` | POST | write | web | - | - |
| `profilesAdmin.deleteProfileMasterData` | POST | write | web | - | - |
| `profilesAdmin.getAdditionalDataResponseRevisionHistory` | GET | staff | web | - | - |
| `profilesAdmin.getAdditionalDataResponsesForOwner` | GET | staff | web | - | - |
| `profilesAdmin.getLockHistory` | GET | staff | web | - | - |
| `profilesAdmin.getUserData` | GET | staff | web | - | - |
| `resources.listAvailableResources` | GET | staff | web | - | - |
| `resources.listResources` | GET | staff | web | - | - |
| `roleAdministration.listassignedgrouproles` | GET | write | web | - | - |
| `roleAdministration.listassignedrolesforgroups` | POST | write | web | - | - |
| `roleAdministration.listroledefinitions` | GET | write | web | - | - |
| `search.findGeneric` | GET | messages | used | `Text`, `Limit`, `Offset`, `DocTypeCount`, `DocType` (optional) | - |
| `search.findGroups` | GET | read | used | `text`, `limit` | - |
| `search.findMessage` | POST | messages | used | - | `text`, `typeahead`, `exactTerm`, `activeChildrenInstitutionProfileIds`, `institutionCodes`, `limit`, `offset`, `commonInboxID`, `filterBy`, `sortBy`, `sortDirection`, `threadSubject`, `messageContent`, `fromDate`, `toDate`, `threadCreators`, `participants`, `hasAttachments` |
| `search.findProfilesAndGroups` | GET | read | used | `Text`, `Limit`, `Typeahead` | - |
| `search.findRecipients` | GET | read | used | `Text`, `Limit`, `TypeAhead`, `DocTypes` (optional), `PortalRoles` (optional) | - |
| `session.keepAlive` | GET | write | web | - | - |
| `session.stepUpCurrentSession` | POST | write | web | - | - |
