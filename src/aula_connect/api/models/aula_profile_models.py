"""The user's and the children's profiles, their presence, and the login's result."""

from dataclasses import dataclass
from datetime import datetime, time
from typing import List, Optional
@dataclass
class AulaProfilePicture:
    """A profile's picture."""
    id: int
    bucket: Optional[str|None] = None
    is_image_scaling_pending: Optional[bool|None] = None
    key: Optional[str|None] = None
    url: Optional[str|None] = None

@dataclass
class AulaInstitutionProfile:
    """A profile at an institution."""
    id: int
    institution_code: str
    institution_name: str
    metadata: Optional[str|None] = None

@dataclass
class AulaInstitutionGroup:
    """A group at an institution, such as a class."""
    id: int
    name: str
    short_name: str

@dataclass
class AulaProfileRelation:
    """The main group of a child."""
    child_id: int
    main_group: AulaInstitutionGroup

@dataclass
class AulaChildProfile:
    """A child of the user."""
    first_name: str
    id: int
    institution_code: str
    institution_profile: AulaInstitutionProfile
    main_group: AulaInstitutionGroup
    name: str
    profile_id: int
    short_name: str
    user_id: str
    profile_picture: Optional[AulaProfilePicture|None] = None

@dataclass
class AulaProfile:
    """The user's profile, with the children and the institution profiles."""
    children: List[AulaChildProfile]
    first_name: str
    institution_profiles: List[AulaInstitutionProfile]
    name: str
    profile_id: int
    user_id: str
    is_latest_data_policy_accepted: Optional[bool|None] = None

@dataclass
class AulaToken:
    """A widget token, and when it was fetched."""
    bearer_token: str
    timestamp: datetime
    expires_at: Optional[datetime] = None
    """JWT exp claim decoded as datetime, or None if not parseable."""

@dataclass
class AulaWidget:
    """A widget an institution has."""
    id: int
    name: str
    widget_id: str
    description: Optional[str|None] = None
    icon: Optional[str|None] = None
    widget_supplier: Optional[str|None] = None
    widget_version: Optional[str|None] = None

@dataclass
class AulaLocation:
    """Where a child is, as the daily overview says."""
    description: str
    id: int
    name: str
    end_datetime: Optional[datetime|None] = None
    icon: Optional[str|None] = None
    start_datetime: Optional[datetime|None] = None

@dataclass
class AulaDailyOverview:
    """A child's presence today."""
    id: int
    institution_profile: AulaInstitutionProfile
    status: int
    check_in_time_expected: Optional[time|None] = None
    check_in_time: Optional[time|None] = None
    check_out_time_expected: Optional[time|None] = None
    check_out_time: Optional[time|None] = None
    comment: Optional[str|None] = None
    exit_with: Optional[str|None] = None
    is_default_check_in_time_expected: Optional[bool|None] = None
    is_default_check_out_time_expected: Optional[bool|None] = None
    is_planned_times_outside_opening_hours: Optional[bool|None] = None
    location: Optional[AulaLocation|None] = None
    spare_time_activity: Optional[str|None] = None
    # Aula's activityType, editablePresenceStates and sleepIntervals are left out: they have
    # only ever been seen as 0 or empty, so their form is not known.

@dataclass
class AulaLoginData:
    """What a login read: the profiles, the widgets and the API version."""
    api_version: int
    profiles: List[AulaProfile]
    widgets: List[AulaWidget]