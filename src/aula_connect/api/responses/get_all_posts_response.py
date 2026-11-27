"""Aula's answer to posts.getAllPosts and posts.getById, as far as it is read."""

from typing import List, NotRequired, TypedDict

from .common_data import AulaStatusData


class AulaPostContentData(TypedDict):
    """A post's text."""
    html: NotRequired[str|None]


class AulaPostFileData(TypedDict):
    """A file attached to a post, or a picture's file."""
    name: NotRequired[str|None]
    url: NotRequired[str|None]


class AulaPostMediaData(TypedDict):
    """A picture or a video attached to a post."""
    mediaType: NotRequired[str|None]
    thumbnailUrl: NotRequired[str|None]
    largeThumbnailUrl: NotRequired[str|None]
    file: NotRequired[AulaPostFileData|None]


class AulaPostAttachmentData(TypedDict):
    """What is attached to a post."""
    id: NotRequired[int|None]
    name: NotRequired[str|None]
    file: NotRequired[AulaPostFileData|None]
    media: NotRequired[AulaPostMediaData|None]


class AulaPostInstitutionData(TypedDict):
    """The institution a post's author is at."""
    institutionName: NotRequired[str|None]


class AulaPostOwnerData(TypedDict):
    """Who wrote a post."""
    fullName: NotRequired[str|None]
    institution: NotRequired[AulaPostInstitutionData|None]


class AulaPostGroupData(TypedDict):
    """A group a post is shared with."""
    name: NotRequired[str|None]


class AulaPostRelatedProfileData(TypedDict):
    """A profile of the user's that a post concerns, such as a guardian's child."""
    id: NotRequired[int|None]
    role: NotRequired[str|None]


class AulaPostData(TypedDict):
    """A post."""
    id: NotRequired[int|None]
    title: NotRequired[str|None]
    content: NotRequired[AulaPostContentData|None]
    timestamp: NotRequired[str|None]
    publishAt: NotRequired[str|None]
    editedAt: NotRequired[str|None]
    expireAt: NotRequired[str|None]
    isImportant: NotRequired[bool|None]
    importantFrom: NotRequired[str|None]
    importantTo: NotRequired[str|None]
    commentCount: NotRequired[int|None]
    attachments: NotRequired[List[AulaPostAttachmentData]|None]
    ownerProfile: NotRequired[AulaPostOwnerData|None]
    sharedWithGroups: NotRequired[List[AulaPostGroupData]|None]
    relatedProfiles: NotRequired[List[AulaPostRelatedProfileData]|None]


class AulaPostsData(TypedDict):
    """A page of posts, the newest first."""
    posts: NotRequired[List[AulaPostData]|None]
    hasMorePosts: NotRequired[bool|None]
    profileLastSeenPostDate: NotRequired[str|None]


class AulaGetAllPostsResponse(TypedDict):
    """The answer to posts.getAllPosts."""
    data: AulaPostsData
    status: AulaStatusData
    version: int


class AulaGetPostByIdResponse(TypedDict):
    """The answer to posts.getById."""
    data: AulaPostData
    status: AulaStatusData
    version: int
