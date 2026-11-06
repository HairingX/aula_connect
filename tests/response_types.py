"""Where a JSON answer differs from the type the library declares for it."""

from __future__ import annotations

import types
import typing
from typing import Any, NotRequired, Required, cast, get_args, get_origin, get_type_hints, is_typeddict

from aula_connect.api.responses import (
    get_birthday_events_for_institutions,
    get_daily_overview_response,
    get_events_by_profile_ids_and_resource_ids,
    get_message_threads_response,
    get_messages_for_thread_response,
    get_notifications_response,
    get_profile_context_response,
    get_profile_master_data_response,
    get_profiles_by_login_response,
)

RESPONSE_TYPES: dict[str, Any] = {
    "profiles.getProfilesByLogin": get_profiles_by_login_response.AulaGetProfilesByLoginResponse,
    "profiles.getProfileContext": get_profile_context_response.AulaGetProfileContextResponse,
    "profiles.getProfileMasterData": get_profile_master_data_response.AulaGetProfileMasterDataResponse,
    "presence.getDailyOverview": get_daily_overview_response.AulaGetDailyOverviewResponse,
    "messaging.getThreads": get_message_threads_response.AulaGetMessageThreadsResponse,
    "messaging.getMessagesForThread": get_messages_for_thread_response.AulaGetMessagesForThreadResponse,
    "notifications.getNotificationsForActiveProfile": get_notifications_response.AulaGetNotificationsResponse,
    "calendar.getEventsByProfileIdsAndResourceIds": get_events_by_profile_ids_and_resource_ids.AulaGetEventsByProfileIdsAndResourceIdsResponse,
    "calendar.getBirthdayEventsForInstitutions": get_birthday_events_for_institutions.AulaGetBirthdayEventsForInstitutionsResponse,
}
"""The declared type of the answer to each method of Aula's API."""


def _unwrapped(declared: Any) -> tuple[Any, bool]:
    required = True
    while get_origin(declared) in (NotRequired, Required):
        required = get_origin(declared) is Required
        declared = get_args(declared)[0]
    return declared, required


def _choices(declared: Any) -> list[Any]:
    return list(get_args(declared)) if get_origin(declared) in (typing.Union, types.UnionType) else [declared]


def _fits(declared: Any, value: object) -> bool:
    if declared is Any or declared is object:
        return True
    if declared is type(None):
        return value is None
    origin = get_origin(declared) or declared
    if origin is typing.Literal:
        return value in get_args(declared)
    if is_typeddict(declared) or origin is dict:
        return isinstance(value, dict)
    if origin is list:
        return isinstance(value, list)
    if declared is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, origin)


def mismatches(declared: Any, value: object, path: str = "") -> list[str]:
    """Each place in `value` whose type the declared type does not admit, and each required key it lacks.

    Keys the declared type does not name are left out, as the library reads only what it needs.
    """
    declared, _ = _unwrapped(declared)
    choices = _choices(declared)
    fitting = [choice for choice in choices if _fits(choice, value)]
    if not fitting:
        names = " | ".join(getattr(choice, "__name__", str(choice)) for choice in choices)
        return [f"{path or '.'}: declared {names}, got {type(value).__name__}"]
    found: list[str] = []
    for choice in fitting:
        if is_typeddict(choice) and isinstance(value, dict):
            fields = cast(dict[str, object], value)
            hints = get_type_hints(choice, include_extras=True)
            for key, hint in hints.items():
                inner, required = _unwrapped(hint)
                if key not in fields:
                    if required and key in choice.__required_keys__:
                        found.append(f"{path}.{key}: missing")
                    continue
                found += mismatches(inner, fields[key], f"{path}.{key}")
        elif get_origin(choice) is list and isinstance(value, list):
            [item] = get_args(choice) or [Any]
            for entry in cast(list[object], value):
                found += mismatches(item, entry, f"{path}[]")
    return sorted(set(found))
