"""Aula's answer to profiles.getProfileMasterData."""

from typing import List, NotRequired, TypedDict

from .common_data import AulaStatusData

class AulaProfileMasterDataInstitutionGroupData(TypedDict):
    """A group at an institution, such as a class."""
    name: NotRequired[str|None]
    id: int
    shortName: NotRequired[str|None]

class AulaProfileMasterDataRelationData(TypedDict):
    """A child, with its main group."""
    id: NotRequired[int|None]
    mainGroup: NotRequired[AulaProfileMasterDataInstitutionGroupData|None]

class AulaProfileMasterDataInstitutionProfileData(TypedDict):
    """The user's profile at an institution, with the children."""
    relations: NotRequired[List[AulaProfileMasterDataRelationData]|None]

class AulaGetProfileMasterData(TypedDict):
    """The institution profiles."""
    institutionProfiles: NotRequired[List[AulaProfileMasterDataInstitutionProfileData]|None]

class AulaGetProfileMasterDataResponse(TypedDict):
    """The answer, with the institution profiles."""
    data: AulaGetProfileMasterData
    status: AulaStatusData
    version: int
