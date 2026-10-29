"""Aula's answer to profiles.getProfilesByLogin."""

from typing import NotRequired, TypedDict, List

from .common_data import AulaProfilePictureData, AulaStatusData

class AulaInstitutionProfileData(TypedDict):
    """A profile at an institution."""
    id: NotRequired[int|None]
    institutionCode: NotRequired[str|None]
    institutionName: NotRequired[str|None]
    metadata: NotRequired[str|None]

class AulaChildData(TypedDict):
    """A child of the user."""
    id: NotRequired[int|None]
    institutionCode: NotRequired[str|None]
    institutionProfile: NotRequired[AulaInstitutionProfileData|None]
    name: NotRequired[str|None]
    profileId: NotRequired[int|None]
    profilePicture: NotRequired[AulaProfilePictureData|None]
    shortName: NotRequired[str|None]
    userId: NotRequired[str|None]

class AulaProfileData(TypedDict):
    """The user's profile."""
    children: NotRequired[List[AulaChildData]|None]
    displayName: NotRequired[str|None]
    institutionProfiles: NotRequired[List[AulaInstitutionProfileData]|None]
    isLatestDataPolicyAccepted: NotRequired[bool|None]
    profileId: NotRequired[int|None]

class AulaGetProfilesByLoginResponseData(TypedDict):
    """The profiles."""
    profiles: NotRequired[List[AulaProfileData]|None]

class AulaGetProfilesByLoginResponse(TypedDict):
    """The answer, with the profiles."""
    data: AulaGetProfilesByLoginResponseData
    status: AulaStatusData
    version: int