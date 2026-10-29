"""Aula's answer to messaging.getMessagesForThread."""

from typing import NotRequired, TypedDict, List

from .common_data import AulaStatusData
from .get_message_threads_response import AulaThreadRecipientData, AulaMessageTextData

class AulaMessageData(TypedDict):
    """A message."""
    canReplyToMessage: bool
    hasAttachments: bool
    id: str
    messageType: str
    sendDateTime: str
    sender: NotRequired[AulaThreadRecipientData|None]
    text: NotRequired[AulaMessageTextData|None]

class AulaMessagesForThreadData(TypedDict):
    """A page of a thread's messages."""
    extraRecipientsCount: NotRequired[int|None]
    hasSecureDocuments: bool
    id: int
    institutionCode: str
    isArchived: bool
    lastReadMessageId: str
    marked: bool
    messages: List[AulaMessageData]
    moreMessagesExist: bool
    muted: bool
    page: int
    recipients: List[AulaThreadRecipientData]
    sensitive: bool
    subject: str
    threadCreator: AulaThreadRecipientData
    threadStartedDateTime: str
    totalMessageCount: int

class AulaGetMessagesForThreadResponse(TypedDict):
    """The answer, with a page of messages."""
    data: AulaMessagesForThreadData
    status: AulaStatusData
    version: int
