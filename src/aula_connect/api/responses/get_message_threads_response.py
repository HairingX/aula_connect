"""Aula's answer to messaging.getThreads."""

from typing import TypedDict, List

from .common_data import AulaStatusData

class AulaMessageTextData(TypedDict):
    """The text of a message."""
    html: str

class AulaThreadRecipientData(TypedDict):
    """A sender or recipient."""
    answerDirectlyName: str
    fullName: str
    metadata: str

class AulaThreadChildData(TypedDict):
    """A child a thread is about."""
    displayName: str
    profileId: int
    shortName: str

class AulaThreadLatestMessageData(TypedDict):
    """The newest message of a thread."""
    id: str
    sendDateTime: str
    text: AulaMessageTextData

class AulaThreadData(TypedDict):
    """A thread."""
    creator: AulaThreadRecipientData
    extraRecipientsCount: int
    id: int
    institutionCode: str
    isArchived: bool
    isThreadOrSubscriptionDeleted: bool
    latestMessage: AulaThreadLatestMessageData
    marked: bool
    muted: bool
    read: bool
    recipients: List[AulaThreadRecipientData]
    regardingChildren: List[AulaThreadChildData]
    sensitive: bool
    startedTime: str
    subject: str

class AulaThreadsData(TypedDict):
    """A page of threads."""
    moreMessagesExist: bool
    page: int
    threads: List[AulaThreadData]

class AulaGetMessageThreadsResponse(TypedDict):
    """The answer, with a page of threads."""
    data: AulaThreadsData
    status: AulaStatusData
    version: int
