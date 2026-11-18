# The methods of Aula's API

Aula's API is one address, `https://www.aula.dk/api/v<version>`, asked with the method's name in
`method=` and its parameters beside it. `aula_connect.methods` lists every method known to exist,
how it is asked, and the names Aula has no method by, so that none is guessed. `AulaClient.read`
asks a listed method with its verb, and never one of a kind it does not ask.

- **Spelling.** Aula tells names apart by their case: `profiles.getContactList` is no method, where
  `profiles.getContactlist` is. A name is listed as Aula spells it. The parameters' spelling
  varies from method to method too, such as `Start` against `start`; each is listed as asked.
- **Verb.** Most methods are asked with GET. A few that only read are asked with POST and a JSON
  body, such as `calendar.getEventsByProfileIdsAndResourceIds`.
- **Kind.** `read` only gets. `messages` gets the text of messages and `secure_documents` secure
  documents, either of which may be marked sensitive; `token` hands out a token, a credential;
  `write` changes Aula. Only `read` is ever asked by `read`.
- **Evidence.** `seen`: Aula answered it, as listed, in this library's own reads. `used`: a
  maintained client of Aula's API asks it, as listed; it is not seen answered here.
- **Errors.** Aula answers a name it has no method by with code 10, and parameters it does not
  take with HTTP 400 and code 40.

A name not listed may still be one Aula has. `read` asks one where it is named as a method that
gets, `<area>.get<What>` or `<area>.find<What>`, and is about neither messages nor secure documents.

The methods marked `used`, their parameters and the names Aula has no method by come from
[nickknissen/aula](https://github.com/nickknissen/aula) (MIT licence, "Copyright (c) 2025 Nick"),
as of its commit 6a79d3e; `calendar.getEventDetail` was found to be no method by this library.

<!-- The tables below are checked against aula_connect.methods by the tests. -->

## Methods

| Method | Verb | Kind | Evidence | Query | Body |
|---|---|---|---|---|---|
| `aulaToken.getAulaToken` | GET | token | seen | `widgetId` | - |
| `calendar.addVacation` | POST | write | used | - | `childIds`, `intervals`, `comment` |
| `calendar.getBirthdayEventsForGroup` | GET | read | used | `groupId`, `start`, `end` | - |
| `calendar.getBirthdayEventsForInstitutions` | GET | read | seen | `instCodes[]`, `start`, `end` | - |
| `calendar.getDailyAggregatedEvents` | GET | read | used | `InstProfileIds[]`, `Start`, `End` | - |
| `calendar.getDailyEventCountForGroup` | GET | read | used | `GroupId`, `Start`, `End` | - |
| `calendar.getEventById` | GET | read | used | `eventId`, `occurrenceDateTime` (optional) | - |
| `calendar.geteventsbygroupid` | GET | read | used | `groupId`, `start`, `end` | - |
| `calendar.getEventsByProfileIdsAndResourceIds` | POST | read | seen | - | `instProfileIds`, `resourceIds`, `start`, `end` |
| `calendar.getEventsForInstitutions` | GET | read | used | `Start`, `End`, `InstCodes[]` | - |
| `calendar.getEventTypes` | GET | read | used | `Type`, `FilterInstitutionCodes[]` (optional) | - |
| `calendar.getImportantDates` | GET | read | used | `limit`, `includeToday` | - |
| `comments.getComments` | GET | read | used | `ParentType`, `ParentId`, `Limit` | - |
| `commonFiles.getCommonFiles` | GET | read | used | `index`, `limit`, `institutionCodes[]` | - |
| `consents.getConsentResponses` | GET | read | used | `institutionProfileIds[]` | - |
| `documents.getSecureDocuments` | POST | secure_documents | used | - | `index`, `limit`, `filterInstitutionProfileIds` |
| `gallery.getAlbums` | GET | read | used | `index`, `limit`, `sortOn`, `orderDirection`, `filterBy`, `filterInstProfileIds[]` | - |
| `gallery.getMedia` | GET | read | used | `albumId`, `index`, `limit`, `sortOn`, `orderDirection`, `filterBy`, `filterInstProfileIds[]` | - |
| `gallery.getMediaById` | GET | read | used | `id` | - |
| `gallery.getMediaByInstitutionProfileId` | GET | read | used | `institutionProfileId`, `Limit` | - |
| `groups.getGroupById` | GET | read | used | `groupId` | - |
| `groups.getGroupsByContext` | GET | read | used | `childInstitutionProfileIds[]` (optional), `institutionCodes[]` (optional) | - |
| `groups.getMembershipsLight` | GET | read | used | `groupId`, `portalRoles[]` (optional) | - |
| `messaging.getAutoReply` | GET | read | used | - | - |
| `messaging.getCommonInboxes` | GET | read | used | `InstitutionProfileIds[]` (optional) | - |
| `messaging.getFolders` | GET | read | used | `IncludeDeletedFolders` | - |
| `messaging.getMessageInfoLight` | GET | messages | used | `ThreadId`, `MessageId` | - |
| `messaging.getMessagesForThread` | GET | messages | seen | `threadId`, `page` | - |
| `messaging.getThreads` | GET | messages | seen | `sortOn`, `orderDirection`, `page` | - |
| `messaging.getThreadsInBundle` | GET | messages | used | `BundleId` | - |
| `messaging.setLastReadMessage` | POST | write | used | - | `threadId`, `messageId`, `commonInboxId`, `otpInboxId` |
| `notifications.getNotificationSettingsForActiveProfile` | GET | read | used | - | - |
| `notifications.getNotificationsForActiveProfile` | GET | read | seen | `activeChildrenIds[]`, `activeInstitutionCodes[]` | - |
| `posts.getAllPosts` | GET | read | used | `parent`, `index`, `limit`, `institutionProfileIds[]` | - |
| `posts.getById` | GET | read | used | `id` | - |
| `presence.getActivityOverview` | GET | read | used | `institutionProfileIds[]`, `week`, `year` | - |
| `presence.getDailyOverview` | GET | read | seen | `childIds[]` | - |
| `presence.getPickupResponsibles` | GET | read | used | `uniStudentIds[]` | - |
| `presence.getPresenceConfigurationByChildIds` | GET | read | used | `childIds[]` | - |
| `presence.getPresenceRegistrationDetail` | GET | read | used | `id` | - |
| `presence.getPresenceRegistrations` | GET | read | used | `institutionProfileIds[]`, `fromDate`, `toDate` | - |
| `presence.getPresenceStates` | GET | read | used | `institutionProfileIds[]` (optional) | - |
| `presence.getPresenceTemplates` | GET | read | used | `filterInstitutionProfileIds[]`, `fromDate`, `toDate` | - |
| `presence.getVacationRegistrationsByChildren` | GET | read | used | `childIds[]` | - |
| `presence.updatePresenceTemplate` | POST | write | used | - | `institutionProfileId`, `byDate`, `presenceActivity`, `comment`, `repeatPattern`, `expiresAt`, `id` (optional) |
| `presence.updateStatusByInstitutionProfileIds` | POST | write | used | - | `institutionProfileIds`, `status` |
| `profiles.getContactlist` | GET | read | used | `groupId`, `filter`, `field`, `page`, `order` | - |
| `profiles.getContactParents` | GET | read | used | `page`, `order` | - |
| `profiles.getProfileContext` | GET | read | seen | `portalrole` | - |
| `profiles.getProfileMasterData` | GET | read | seen | `instProfileIds[]`, `fromAdministration` | - |
| `profiles.getProfilesByLogin` | GET | read | seen | - | - |
| `profiles.keepAlive` | GET | write | used | - | - |
| `search.findGeneric` | GET | messages | used | `Text`, `Limit`, `Offset`, `DocTypeCount`, `DocType` (optional) | - |
| `search.findGroups` | GET | read | used | `text`, `limit` | - |
| `search.findMessage` | POST | messages | used | - | `text`, `typeahead`, `exactTerm`, `activeChildrenInstitutionProfileIds`, `institutionCodes`, `limit`, `offset`, `commonInboxID`, `filterBy`, `sortBy`, `sortDirection`, `threadSubject`, `messageContent`, `fromDate`, `toDate`, `threadCreators`, `participants`, `hasAttachments` |
| `search.findProfilesAndGroups` | GET | read | used | `Text`, `Limit`, `Typeahead` | - |
| `search.findRecipients` | GET | read | used | `Text`, `Limit`, `TypeAhead`, `DocTypes` (optional), `PortalRoles` (optional) | - |

## Names Aula has no method by

| Name | The method meant |
|---|---|
| `calendar.getEventDetail` | `calendar.getEventById` |
| `presence.getVacationRegistrations` | `presence.getVacationRegistrationsByChildren` |
| `profiles.getContactList` | `profiles.getContactlist` |
| `search.searchGroups` | `search.findGroups` |
| `secureDocument.getCommonFiles` | `commonFiles.getCommonFiles` |
| `secureDocument.getSecureDocuments` | `documents.getSecureDocuments` |
