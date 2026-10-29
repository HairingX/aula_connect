"""Aula's message threads and their messages."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import List, Optional


class AulaMessageType(StrEnum):
    """What a message in a thread is."""
    RECIPIENTS_ADDED= "RecipientsAdded"
    RECIPIENTS_REMOVED = "RecipientsRemoved"
    MESSAGE = "Message"

@dataclass
class AulaThreadRecipient:
    """A sender or recipient of messages."""
    answer_directly_name: str
    full_name: str
    metadata: str

@dataclass
class AulaMessageText:
    """The text of a message."""
    html: str

@dataclass
class AulaMessage:
    """A message of a thread."""
    id: str
    message_type: str
    send_datetime: datetime
    can_reply_to_message: Optional[bool|None] = None
    has_attachments: Optional[bool|None] = None
    recipients: Optional[List[AulaThreadRecipient]|None] = None
    sender: Optional[AulaThreadRecipient|None] = None
    text: Optional[AulaMessageText|None] = None

@dataclass
class AulaMessagePreview:
    """The newest message of a thread, as the list of threads shows it."""
    id: str
    send_datetime: datetime
    text: Optional[AulaMessageText|None] = None

@dataclass
class AulaThreadRegardingChild:
    """A child a thread is about."""
    display_name: str
    profile_id: int
    short_name: str

@dataclass
class AulaMessageThread:
    """A thread of messages."""
    extra_recipients_count: int
    id: int
    institution_code: str
    is_archived: bool
    is_thread_or_subscription_deleted: bool
    marked: bool
    muted: bool
    read: bool
    recipients: List[AulaThreadRecipient]
    regarding_children: List[AulaThreadRegardingChild]
    sensitive: bool
    started_datetime: datetime
    subject: str
    creator: Optional[AulaThreadRecipient|None] = None
    latest_message: Optional[AulaMessagePreview|None] = None