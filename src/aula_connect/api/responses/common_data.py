"""Parts of Aula's answers that many of them share."""

from typing import NotRequired, TypedDict


class AulaStatusData(TypedDict):
    """The status of an answer."""
    code: int
    message: str

class AulaProfilePictureData(TypedDict):
    """A profile picture."""
    bucket: NotRequired[str|None]
    id: NotRequired[str|None]
    isImageScalingPending: NotRequired[bool|None]
    key: NotRequired[str|None]
    url: NotRequired[str|None]