"""Aula's answer to profiles.getProfileContext."""

from typing import List, NotRequired, TypedDict

from .common_data import AulaProfilePictureData, AulaStatusData

class AulaProfileContextInstitutionData(TypedDict):
    """An institution of the user, with the children there."""
    institutionCode: NotRequired[str|None]
    institutionName: NotRequired[str|None]
    municipalityCode: NotRequired[str|None]
    municipalityName: NotRequired[str|None]
    type: NotRequired[str|None]

class AulaProfileContextRelationData(TypedDict):
    """A relation of the user's at an institution."""
    firstName: NotRequired[str|None]
    fullName: NotRequired[str|None]
    gender: NotRequired[str|None]
    id: NotRequired[int|None]
    institution: NotRequired[AulaProfileContextInstitutionData|None]
    lastName: NotRequired[str|None]
    mainGroupName: NotRequired[str|None]
    metadata: NotRequired[str|None]
    profileId: NotRequired[int|None]
    profilePicture: NotRequired[AulaProfilePictureData|None]
    shortName: NotRequired[str|None]
    uniPersonId: NotRequired[int|None]

class AulaProfileContextInstitutionProfileData(TypedDict):
    """The user's profile at an institution."""
    birthday: NotRequired[str|None]
    email: NotRequired[str|None]
    encryptionKey: NotRequired[str|None]
    firstName: NotRequired[str|None]
    fullName: NotRequired[str|None]
    gender: NotRequired[str|None]
    id: NotRequired[int|None]
    institution: NotRequired[AulaProfileContextInstitutionData|None]
    lastName: NotRequired[str|None]
    metadata: NotRequired[str|None]
    phone: NotRequired[str|None]
    profileId: NotRequired[int|None]
    profilePicture: NotRequired[AulaProfilePictureData|None]
    relations: NotRequired[List[AulaProfileContextRelationData]|None]
    shortName: NotRequired[str|None]
    uniPersonId: NotRequired[int|None]

class AulaProfileContextChildData(TypedDict):
    """A child at an institution."""
    id: int
    institutionCode: NotRequired[str|None]
    name: NotRequired[str|None]
    profileId: NotRequired[int|None]
    profilePicture: NotRequired[AulaProfilePictureData|None]
    shortName: NotRequired[str|None]
    userId: str

class AulaProfileContextInstitutionDetailsData(TypedDict):
    """An institution."""
    children: NotRequired[List[AulaProfileContextChildData]|None]
    institutionCode: NotRequired[str|None]
    institutionProfileId: NotRequired[int|None]
    institutionType: NotRequired[str|None]
    mailboxId: NotRequired[int|None]
    municipalityCode: NotRequired[str|None]
    name: NotRequired[str|None]
    shortName: NotRequired[str|None]

class AulaProfileContextWidgetData(TypedDict):
    """A widget."""
    description: NotRequired[str|None]
    icon: NotRequired[str|None]
    id: NotRequired[int|None]
    name: NotRequired[str|None]
    widgetId: NotRequired[str|None]
    widgetSupplier: NotRequired[str|None]
    widgetVersion: NotRequired[str|None]

class AulaProfileContextWidgetConfigurationData(TypedDict):
    """Where a widget is shown."""
    id: NotRequired[int|None]
    widget: AulaProfileContextWidgetData

class AulaProfileContextPageConfigurationData(TypedDict):
    """The widgets shown."""
    widgetConfigurations: List[AulaProfileContextWidgetConfigurationData]

class AulaProfileContextData(TypedDict):
    """The user's context: who it is, the institutions and the widgets."""
    homePhonenumber: NotRequired[str|None]
    id: NotRequired[int|None]
    institutionProfile: NotRequired[AulaProfileContextInstitutionProfileData|None]
    institutions: NotRequired[List[AulaProfileContextInstitutionDetailsData]|None]
    mobilePhonenumber: NotRequired[str|None]
    pageConfiguration: AulaProfileContextPageConfigurationData
    userId: str
    workPhonenumber: NotRequired[str|None]

class AulaGetProfileContextResponse(TypedDict):
    """The answer, with the user's context."""
    data: AulaProfileContextData
    status: AulaStatusData
    version: int
