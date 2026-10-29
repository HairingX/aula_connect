"""The client of Aula's API and of its widgets' (Meebook, EasyIQ, MinUddannelse), on an access token."""

import base64
import binascii
import asyncio
from dataclasses import dataclass
from http import HTTPStatus
import aiohttp
from typing import Any, Awaitable, Callable, Dict, Iterable, List, cast
from datetime import datetime, timedelta, date, timezone
import json
import logging
from ..http import HttpResponse, HttpSession
from ..redact import redact
from .aula_errors import AulaCredentialError, AulaApiError
from .models.constants import AulaWidgetId
from .models.module import (
    AULA_NOTIFICATION_TYPES,
    AulaBirthdayEvent,
    AulaBirthdayParser,
    AulaCalendarEvent,
    AulaCalendarParser,
    AulaChildProfile,
    AulaDailyOverview,
    AulaEasyiqWeeklyPlan,
    AulaEasyiqWeekplanParser,
    AulaInstitutionProfile,
    AulaLoginData,
    AulaMessage,
    AulaMessageThread,
    AulaMessageThreadParser,
    AulaNewsletterParser,
    AulaNotificationParser,
    AulaProfile,
    AulaProfileParser,
    AulaToken,
    AulaWeeklyNewsletter,
    AulaWeeklyPlan,
    AulaWeeklyPlanParser,
    AulaWidget,
)
from .responses.get_profile_context_response import AulaGetProfileContextResponse
from .responses.get_profile_master_data_response import AulaGetProfileMasterDataResponse
from .responses.get_profiles_by_login_response import AulaGetProfilesByLoginResponse
from .responses.get_weekly_plans_response import AulaGetWeeklyPlansResponse
from .const import (
    API,
    API_VERSION,
    EASYIQ_API,
    MEEBOOK_API,
    MIN_UDDANNELSE_API,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_MAX_ATTEMPTS = 3
"""How many times a request is sent before a network or server error is given up on."""
REQUEST_TIMEOUT = 30
"""Seconds a single request may take."""
TOKEN_EXPIRATION_TIME = timedelta(minutes=5)
"""How long a widget token is used before a new one is fetched. Aula's own expiry of its widget
tokens cannot be relied on, as it is now and then already past when it hands one out."""
RECOVERY_COOLDOWN = timedelta(minutes=10)
"""The least time between two recoveries of a widget token. During an outage at Aula, recovering
again only churns its token endpoint."""


def _describe_token(token: 'AulaToken | None') -> str:
    """A widget token's age and expiry, as a log tells them, without the token itself."""
    if token is None:
        return "token=None"
    now = datetime.now(timezone.utc)
    age = (now - token.timestamp).total_seconds()
    if token.expires_at is None:
        return f"token age={age:.0f}s, JWT exp=undecoded"
    ttl = (token.expires_at - now).total_seconds()
    state = "EXPIRED" if ttl <= 0 else "valid"
    return f"token age={age:.0f}s, JWT exp={token.expires_at.isoformat()}, TTL={ttl:.0f}s ({state})"


def _decode_jwt_exp(jwt_token: str) -> datetime | None:
    """The expiry (exp) of a JWT, unverified, None where it has none that can be read."""
    try:
        parts = jwt_token.split('.')
        if len(parts) != 3:
            return None
        payload = parts[1]
        # JWT base64url encoding has no padding — add it back
        payload += '=' * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        if not isinstance(claims, dict):
            return None
        exp = cast(dict[str, object], claims).get('exp')
        if not isinstance(exp, (int, float)):
            return None
        # exp is in seconds; an issuer that sends milliseconds would otherwise make the token
        # last for ever.
        if exp <= 0 or exp > 32503680000:
            return None
        return datetime.fromtimestamp(exp, tz=timezone.utc)
    except (ValueError, TypeError, binascii.Error, OverflowError, OSError) as e:
        _LOGGER.debug("Could not decode JWT exp claim (%s): %s", type(e).__name__, e)
        return None


class _TokenSession(HttpSession):
    """A session that appends the access token to Aula API URLs."""

    _access_token: str = ""
    api_base: str = API

    def set_access_token(self, token: str) -> None:
        """Send `token` with every request of the Aula API from now on."""
        self._access_token = token

    async def request(self, method: str, url: str, **kwargs: Any) -> HttpResponse:
        """Send a request, with the access token where it is one of the Aula API."""
        if self._access_token and self.api_base in url:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}access_token={self._access_token}"
        return await super().request(method, url, **kwargs)


@dataclass
class _WidgetCall:
    """One read of a widget: its token, and whether it was recovered once already."""

    widgetid: AulaWidgetId
    name: str
    token: AulaToken | None
    recovered: bool = False


class AulaProxyClient:
    """Aula's API and its widgets, read on an access token into typed models.

    A read Aula refuses raises: AulaCredentialError where the access token is refused,
    PermissionError where the data is not the user's, AulaApiError otherwise. An access token
    refused once is renewed through the callback set, where one is, and the read tried again.
    """

    api_version:int = int(API_VERSION)

    _login_result: AulaLoginData | None = None
    _tokens: dict[AulaWidgetId, AulaToken]
    _is_logged_in: bool = False
    _apiurl:str = ""
    _username:str = ""
    _session:_TokenSession
    _token_refresh_callback: Callable[[], Awaitable[bool]] | None = None
    _last_recovery_at: datetime | None = None

    def __init__(self, session: aiohttp.ClientSession, access_token: str, username_for_meebook: str = ""):
        """Read Aula on `session` with `access_token`; Meebook knows the user by `username_for_meebook`."""
        self._username = username_for_meebook
        self._session = _TokenSession(session, timeout=REQUEST_TIMEOUT)
        self._session.set_access_token(access_token)
        self.meebook_api = MEEBOOK_API
        self.easyiq_api = EASYIQ_API
        self.min_uddannelse_api = MIN_UDDANNELSE_API
        self._tokens = dict()
        # One widget token fetch, and one recovery, at a time: reads at once would otherwise
        # each fetch the same token, or each reset the session under the others.
        self._token_refresh_lock = asyncio.Lock()

    def set_token_refresh_callback(self, callback: Callable[[], Awaitable[bool]]) -> None:
        """Renew the access token with `callback` where Aula refuses it.

        The callback answers whether it renewed the token, False for a failure that may pass,
        and raises AulaCredentialError where only a new login helps.
        """
        self._token_refresh_callback = callback

    def use_api(self, api_base: str) -> None:
        """Send the Aula API requests to `api_base`, followed by the version, as for a test server."""
        self._session.api_base = api_base

    def update_token(self, new_token: str) -> None:
        """Update the access token used for API calls."""
        self._session.set_access_token(new_token)

    @staticmethod
    def _is_widget_token_expired_body(response: HttpResponse) -> bool:
        """Whether a 200 OK answer says the widget token has expired, as Aula now and then answers instead of 401."""
        if response.status_code != HTTPStatus.OK:
            return False
        try:
            body = response.json()
        except ValueError:
            return False
        if not isinstance(body, dict):
            return False
        msg = cast(dict[str, object], body).get("message")
        if not isinstance(msg, str):
            return False
        return "expired" in msg.lower()

    async def _full_recovery(self, widgetid: AulaWidgetId) -> AulaToken | None:
        """Fetch a new token for a widget that refused its token, on a new session and access token.

        Aula keeps handing out the same expired widget token as long as the session and the
        access token are the same, so both are renewed first. Recovers at most once in
        RECOVERY_COOLDOWN, giving the token there is meanwhile.

        Raises:
            AulaApiError: No new widget token could be fetched.
            AulaCredentialError: The access token can no longer be renewed.
        """
        async with self._token_refresh_lock:
            now = datetime.now(timezone.utc)
            if self._last_recovery_at is not None and (now - self._last_recovery_at) < RECOVERY_COOLDOWN:
                age = (now - self._last_recovery_at).total_seconds()
                _LOGGER.warning(
                    "Skipping full recovery for widget %s — last recovery was %.0fs ago "
                    "(cooldown %ss). Aula's bug appears persistent; serving cached token.",
                    widgetid, age, RECOVERY_COOLDOWN.total_seconds(),
                )
                return self._tokens.get(widgetid)
            self._last_recovery_at = now

            _LOGGER.info("Triggering full recovery for widget %s (cookies + access_token + session)", widgetid)
            self.reset_session()
            if self._token_refresh_callback is not None and not await self._token_refresh_callback():
                _LOGGER.warning(
                    "OAuth access_token refresh returned False during widget recovery — "
                    "continuing anyway with the existing token",
                )
            try:
                await self.login()
            except Exception as login_err:
                # The widget token may be handed out on a session only partly set up.
                _LOGGER.warning("login() after session reset failed during widget recovery: %s", redact(login_err))
            # The lock is held already.
            return await self._refresh_token_locked(widgetid, force=True)

    def reset_session(self) -> None:
        """Forget the session's cookies, the login and the widget tokens, for a new session at Aula.

        Aula keeps the widget tokens it hands out by its session, not by the access token.
        """
        self._session.clear_cookies()
        self._is_logged_in = False
        self._login_result = None
        self._tokens.clear()
        _LOGGER.info("HTTP session reset (cookies dropped, widget cache cleared, login state reset)")

    def _get_csrf_token(self) -> str | None:
        """The session's CSRF token, which Aula sets at login, None before."""
        return self._session.cookies.get_dict().get("Csrfp-Token")

    async def custom_api_call(self, uri:str, post_data:str|None) -> Any:
        """Call the Aula API at `uri`, after the versioned API URL, with `post_data` as JSON where given.

        Returns:
            Aula's answer; `raw_response` where it is no JSON; `result` saying why where the
            data to post is no JSON.
        """
        headers: Dict[str, str] = {"content-type": "application/json"}
        csrf_token = self._get_csrf_token()
        if csrf_token:
            headers["csrfp-token"] = csrf_token
        url = self._apiurl + uri
        if post_data is None:
            response = await self._session.get(url, headers=headers)
        else:
            try:
                payload = json.loads(post_data)
            except json.JSONDecodeError as e:
                _LOGGER.error("Invalid json supplied as post_data: %s", e)
                return {"result": "Fail - invalid json supplied as post_data"}
            response = await self._session.post(url, headers=headers, json=payload)
        _LOGGER.debug("custom_api_call: HTTP %s", response.status_code)
        try:
            return response.json()
        except ValueError:
            return {"raw_response": response.text}

    async def login(self) -> AulaLoginData:
        """Read the user's profiles, the children's and the widgets the institutions have, where Aula's API is now.

        A client logged in already gives what it read then. Where Aula has moved its API on to
        a newer version, the version is followed.

        Raises:
            AulaCredentialError: Aula refused the access token.
            ConnectionRefusedError: Aula's API could not be found, or answered with an error.
        """
        self._is_logged_in = False
        if self._apiurl:
            try:
                response = await self._session.get(self._apiurl + "?method=profiles.getProfilesByLogin")
                if response.status_code == HTTPStatus.OK:
                    self._is_logged_in = response.json()["status"]["message"] == "OK"
            except (ValueError, KeyError, TypeError, TimeoutError, aiohttp.ClientError) as e:
                _LOGGER.debug("Quick login check failed, will proceed with full login: %s", type(e).__name__)
        if self._is_logged_in and self._login_result is not None:
            return self._login_result

        while True:
            self._apiurl = self._get_aula_api()
            response = await self._session.get(f"{self._apiurl}?method=profiles.getProfilesByLogin")
            if response.status_code == HTTPStatus.OK:
                responsedata: AulaGetProfilesByLoginResponse = response.json()
                profiles = self._parse("profiles", AulaProfileParser.parse_profiles_response, responsedata)
                break
            if response.status_code == HTTPStatus.GONE:
                msg = f"API was expected at {self._apiurl} but responded with HTTP 410. The integration will automatically try a newer version and everything may work fine."
                _LOGGER.debug(msg)
                self.api_version += 1
                if self.api_version - int(API_VERSION) > 10:
                    raise ConnectionRefusedError(msg)
            elif response.status_code == HTTPStatus.FORBIDDEN:
                msg = "Access to Aula API was denied. Please check that you have entered the correct credentials. (Your password automatically expires on regular intervals!)"
                _LOGGER.error(msg)
                raise AulaCredentialError(msg)
            else:
                msg = f"Unknown error occured. Received status code {response.status_code}."
                _LOGGER.error(msg)
                raise ConnectionRefusedError(msg)

        widgets: List[AulaWidget] = []
        if profiles:
            widgets = await self._read_profile_context(profiles)
            await self._read_main_groups(profiles)

        result = AulaLoginData(profiles=profiles, widgets=widgets, api_version=self.api_version)
        self._login_result = result
        _LOGGER.debug("Login found %s profiles and the widgets %s", len(profiles), ", ".join(widget.widget_id for widget in widgets))
        return result

    async def _read_profile_context(self, profiles: List[AulaProfile]) -> List[AulaWidget]:
        """Set the user ids of the profiles and their children, and give the institutions' widgets.

        Raises:
            AulaCredentialError: Aula refused the access token.
        """
        api_method = "profiles.getProfileContext"
        response = await self._session.get(f"{self._apiurl}?method={api_method}&portalrole=guardian")
        if response.status_code == HTTPStatus.FORBIDDEN:
            raise AulaCredentialError(f"Access denied for {api_method}")
        if response.status_code != HTTPStatus.OK:
            _LOGGER.warning("Failed to fetch %s: HTTP %s, some data may be missing", api_method, response.status_code)
            return []
        try:
            responsedata: AulaGetProfileContextResponse = response.json()
            data = responsedata["data"]
            for profile in profiles:
                profile.user_id = data["userId"]
            children = {child.id: child for child in self.flatten_children(profiles)}
            for institutiondata in data.get("institutions") or []:
                for childdata in institutiondata.get("children") or []:
                    child = children.get(childdata["id"])
                    if child:
                        child.user_id = childdata["userId"]
            widgetsdata = [configuration["widget"] for configuration in data["pageConfiguration"]["widgetConfigurations"]]
        except (ValueError, KeyError, TypeError) as e:
            _LOGGER.warning("Failed to parse %s response: %s", api_method, type(e).__name__)
            return []
        try:
            return AulaProfileParser.parse_widgets(widgetsdata)
        except Exception as e:
            _LOGGER.error("Error parsing widgets: %s", type(e).__name__)
            return []

    async def _read_main_groups(self, profiles: List[AulaProfile]) -> None:
        """Set the main group of each child, as far as Aula tells it."""
        api_method = "profiles.getProfileMasterData"
        inst_profile_ids = list(set(str(institution_profile.id) for profile in profiles for institution_profile in profile.institution_profiles))
        response = await self._session.get(f"{self._apiurl}?method={api_method}&instProfileIds[]={"&instProfileIds[]=".join(inst_profile_ids)}&fromAdministration=false")
        if response.status_code != HTTPStatus.OK:
            _LOGGER.warning("Failed to fetch %s: HTTP %s, master group data may be missing", api_method, response.status_code)
            return
        try:
            responsedata: AulaGetProfileMasterDataResponse = response.json()
            relations = AulaProfileParser.parse_profile_master_data_response(responsedata)
        except Exception as e:
            _LOGGER.warning("Failed to parse %s response: %s", api_method, type(e).__name__)
            return
        children = {child.id: child for child in self.flatten_children(profiles)}
        for relation in relations:
            child = children.get(relation.child_id)
            if child:
                child.main_group = relation.main_group

    async def _send(self, name: str, send: Callable[[], Awaitable[HttpResponse]]) -> HttpResponse:
        """Send a request, again where the network or the server failed, up to REQUEST_MAX_ATTEMPTS times.

        Raises:
            aiohttp.ClientError, TimeoutError: The last attempt failed on the network.
        """
        attempt = 1
        while True:
            try:
                response = await send()
            except (TimeoutError, aiohttp.ClientError) as e:
                if attempt >= REQUEST_MAX_ATTEMPTS:
                    raise
                _LOGGER.debug("Request for %s failed (%s), will retry (attempt %s/%s)", name, type(e).__name__, attempt, REQUEST_MAX_ATTEMPTS)
            else:
                # 401 is not tried again with the same token here: the caller renews it first.
                if attempt >= REQUEST_MAX_ATTEMPTS or not 500 <= response.status_code < 600:
                    return response
                _LOGGER.debug("Request failed due to server error, will retry (attempt %s/%s): HTTP %s", attempt, REQUEST_MAX_ATTEMPTS, response.status_code)
            attempt += 1

    async def _read(self, api_method: str, what: str, send: Callable[[], Awaitable[HttpResponse]]) -> Any:
        """Aula's JSON answer to a request of the API, None where it answered with no content.

        Raises:
            AulaCredentialError, PermissionError, AulaApiError: Aula refused the request.
            ConnectionError: The access token could not be renewed, or was refused once renewed.
        """
        response = await self._retry_on_401(await self._send(api_method, send), send)
        if response.status_code != HTTPStatus.OK:
            _LOGGER.debug("Failed to retrieve %s: HTTP %s %s, %s", what, response.status_code, response.reason, redact(response.request.url))
            self._raise_error(response)
            return None
        return response.json()

    @staticmethod
    def _parse[T, D](what: str, parser: Callable[[D], T], data: D) -> T:
        """`data` parsed, the failure logged without the data where it cannot be."""
        try:
            return parser(data)
        except Exception as e:
            _LOGGER.error("Error parsing %s: %s", what, type(e).__name__)
            raise

    async def get_birthday_events(self, profiles: List[AulaChildProfile], start_datetime: datetime, end_datetime: datetime) -> List[AulaBirthdayEvent]:
        """The birthdays at the children's institutions from `start_datetime` to `end_datetime`."""
        if len(profiles) == 0: return []
        inst_profile_codes = list(set(profile.institution_code for profile in profiles))
        start = start_datetime.strftime("%Y-%m-%dT00:00:00.0000%:z").replace("+", "%2B")
        end = end_datetime.strftime("%Y-%m-%dT23:59:59.9990%:z").replace("+", "%2B")
        api_method = "calendar.getBirthdayEventsForInstitutions"
        requesturl = f"{self._apiurl}?method={api_method}&start={start}&end={end}&instCodes[]={str.join("&instCodes[]=", inst_profile_codes)}"
        data = await self._read(api_method, "birthday events", lambda: self._session.get(requesturl))
        if data is None: return []
        events = self._parse("birthday events", AulaBirthdayParser.parse_birthday_event_response, data)
        _LOGGER.debug("Fetched birthday events: %s", len(events))
        return events

    async def get_calendar_events(self, profiles: List[AulaInstitutionProfile], start_datetime: datetime, end_datetime: datetime) -> List[AulaCalendarEvent]:
        """The calendar events of the institution profiles from `start_datetime` to `end_datetime`."""
        if len(profiles) == 0: return []
        headers: Dict[str, str] = {"content-type": "application/json"}
        csrf_token = self._get_csrf_token()
        if csrf_token:
            headers["csrfp-token"] = csrf_token
        post_data: Dict[str, Any] = {
            "instProfileIds": list(set(profile.id for profile in profiles)),
            "resourceIds": [],
            "start": start_datetime.strftime("%Y-%m-%d 00:00:00.0000%:z"),
            "end": end_datetime.strftime("%Y-%m-%d 00:00:00.0000%:z"),
        }
        api_method = "calendar.getEventsByProfileIdsAndResourceIds"
        requesturl = f"{self._apiurl}?method={api_method}"
        data = await self._read(api_method, "calendar events", lambda: self._session.post(requesturl, json=post_data, headers=headers))
        if data is None: return []
        events = self._parse("calendar events", AulaCalendarParser.parse_calendar_event_response, data)
        _LOGGER.debug("Fetched calendar events: %s", len(events))
        return events

    async def get_daily_overviews(self, profiles: List[AulaProfile]) -> List[AulaDailyOverview]:
        """Today's presence of the profiles' children."""
        if len(profiles) == 0: return []
        children = self.flatten_children(profiles)
        child_ids_as_str_list = list(set(str(child.id) for child in children))
        api_method = "presence.getDailyOverview"
        requesturl = f"{self._apiurl}?method={api_method}&childIds[]={str.join("&childIds[]=", child_ids_as_str_list)}"
        data = await self._read(api_method, "daily overviews", lambda: self._session.get(requesturl))
        if data is None: return []
        daily_overviews = self._parse("daily overviews", AulaProfileParser.parse_daily_overview_response, data)
        overview_ids = set(overview.id for overview in daily_overviews)
        for child in children:
            if child.id not in overview_ids:
                _LOGGER.warning("Unable to retrieve presence data from Aula from child with id %s. Some data will be missing from sensor entities.", child.id)
        _LOGGER.debug("Fetched daily overviews: %s", len(daily_overviews))
        return daily_overviews

    async def get_message_threads(self) -> List[AulaMessageThread]:
        """The newest page of the user's message threads."""
        api_method = "messaging.getThreads"
        requesturl = f"{self._apiurl}?method={api_method}&sortOn=date&orderDirection=desc&page=0"
        data = await self._read(api_method, "message threads", lambda: self._session.get(requesturl))
        if data is None: return []
        threads = self._parse("message threads", AulaMessageThreadParser.parse_message_threads_response, data)
        _LOGGER.debug("Fetched message threads: %s", len(threads))
        return threads

    async def get_messages(self, thread: AulaMessageThread) -> List[AulaMessage]:
        """The newest page of the messages of `thread`.

        Raises:
            PermissionError: The thread is sensitive, to be read in Aula only, or not the user's.
            AulaApiError: Aula answered with an error.
        """
        if thread.sensitive: raise PermissionError("Use Aula to read this message.")
        api_method = "messaging.getMessagesForThread"
        requesturl = f"{self._apiurl}?method={api_method}&threadId={thread.id}&page=0"
        data = await self._read(api_method, "messages of a thread", lambda: self._session.get(requesturl))
        if data is None: return []
        messages = self._parse("messages", AulaMessageThreadParser.parse_messages_response, data)
        _LOGGER.debug("Fetched messages: %s", len(messages))
        return messages

    async def get_notifications(self, profiles: List[AulaChildProfile]) -> List[AULA_NOTIFICATION_TYPES]:
        """The user's notifications about the children."""
        if len(profiles) == 0: return []
        child_ids_as_str_list = list(set(str(child.id) for child in profiles))
        institution_profile_codes = list(set(child.institution_code for child in profiles))
        api_method = "notifications.getNotificationsForActiveProfile"
        headers = self._get_aula_header()
        requesturl = f"{self._get_aula_api()}?method={api_method}&activeChildrenIds[]={str.join("&activeChildrenIds[]=",child_ids_as_str_list)}&activeInstitutionCodes[]={str.join("&activeInstitutionCodes[]=",institution_profile_codes)}"
        data = await self._read(api_method, "notifications", lambda: self._session.get(requesturl, headers=headers))
        if data is None: return []
        notifications = self._parse("notifications", AulaNotificationParser.parse_notification_response, data)
        _LOGGER.debug("Fetched notifications: %s", len(notifications))
        return notifications

    async def _widget_send(self, call: _WidgetCall, send: Callable[[AulaToken | None], Awaitable[HttpResponse]]) -> HttpResponse | None:
        """A widget's answer, sent once more after recovering the widget token where it refused it, the first time in a read.

        Aula signals an expired widget token as 401, or now and then as 200 with an "expired" message.
        Returns None where the network failed once recovered.
        """
        response = await self._send(call.name, lambda: send(call.token))
        if call.recovered or not (response.status_code == HTTPStatus.UNAUTHORIZED or self._is_widget_token_expired_body(response)):
            return response
        _LOGGER.warning(
            "%s rejected widget %s token (HTTP %s). Triggering full recovery (cookies + OAuth + re-warm). Rejected %s.",
            call.name, call.widgetid, response.status_code, _describe_token(call.token),
        )
        call.recovered = True
        call.token = await self._full_recovery(call.widgetid)
        _LOGGER.info("After full recovery: %s", _describe_token(call.token))
        try:
            return await send(call.token)
        except (TimeoutError, aiohttp.ClientError) as e:
            _LOGGER.warning("%s retry after full recovery failed with network error: %s", call.name, type(e).__name__)
            return None

    def _widget_failed(self, call: _WidgetCall, response: HttpResponse | None, first: bool) -> None:
        """Raise for a widget's failed answer to the first request of a read; a later one is only logged.

        Raises:
            AulaApiError: The widget refused its token even once recovered, or answered with an error.
            PermissionError: The data is not the user's.
        """
        if response is None:
            return
        _LOGGER.warning("Failed to retrieve %s data: HTTP %s %s", call.name, response.status_code, response.reason)
        if not first:
            return
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            # A widget's 401 is no reason for a new login: the access token is Aula's, not the widget's.
            raise AulaApiError(
                f"{call.name} widget {call.widgetid} returned HTTP 401 even after full recovery "
                f"({_describe_token(call.token)}). This is a confirmed Aula server-side issue."
            )
        self._raise_error(response)

    async def get_weekly_plans(self, profiles: List[AulaChildProfile], from_datetime: datetime, to_datetime: datetime) -> List[AulaWeeklyPlan]:
        """The children's weekly plans in Meebook (widget 0004), week by week from the Monday of `from_datetime` to `to_datetime`."""
        if len(profiles) == 0: return []
        if not self.has_widget(AulaWidgetId.WEEKPLAN_PARENTS): return []
        child_userids_as_str_list = list(set(str(child.user_id) for child in profiles))
        institution_profile_codes = list(set(child.institution_code for child in profiles))
        call = _WidgetCall(AulaWidgetId.WEEKPLAN_PARENTS, "Meebook", await self._get_token(AulaWidgetId.WEEKPLAN_PARENTS))
        requesturl = f"{self.meebook_api}/relatedweekplan/all?currentWeekNumber={{weekno}}&userProfile=guardian&childFilter[]={str.join("&childFilter[]=",child_userids_as_str_list)}&institutionFilter[]={str.join("&institutionFilter[]=",institution_profile_codes)}"

        weeklyplans = list[AulaWeeklyPlan]()
        from_datetime = from_datetime - timedelta(days=from_datetime.weekday())
        first = True
        while from_datetime < to_datetime:
            from_date = from_datetime.date()
            weekno = self._get_aula_week_formatted(from_date)
            url = requesturl.format(weekno=weekno)
            response = await self._widget_send(call, lambda token: self._session.get(url, headers=self._get_meebook_header(token)))
            from_datetime += timedelta(weeks=1)
            if response is None or response.status_code != HTTPStatus.OK:
                self._widget_failed(call, response, first)
                continue
            first = False
            responsedata = response.json()
            # Meebook answers a week it cannot give with an object, such as an error.
            if not isinstance(responsedata, list):
                _LOGGER.warning("Unexpected Meebook response type (%s) for week %s, skipping", type(responsedata).__name__, weekno)
                continue
            plans = cast(list[AulaGetWeeklyPlansResponse], responsedata)
            for respdata in plans:
                respdata["from_date"] = from_date
                respdata["to_date"] = from_date + timedelta(days=6)
            weeklyplans.extend(AulaWeeklyPlanParser.parse_weekly_plans(plans))
        _LOGGER.debug("Fetched meebook weekplan: %s", len(weeklyplans))
        return weeklyplans

    async def _get_guardian_user_id(self) -> str:
        """The user id of the guardian logged in, as the login read it or else as Aula tells it."""
        if self._login_result is not None:
            for profile in self._login_result.profiles:
                if profile.user_id:
                    return profile.user_id
        response = await self._session.get(f"{self._apiurl}?method=profiles.getProfileContext&portalrole=guardian")
        if response.status_code != HTTPStatus.OK:
            raise AulaApiError(f"Failed to fetch guardian user ID: HTTP {response.status_code}")
        return response.json()["data"]["userId"]

    async def get_easyiq_weekly_plans(self, profiles: List[AulaChildProfile], from_datetime: datetime, to_datetime: datetime) -> List[AulaEasyiqWeeklyPlan]:
        """The children's weekly plans in EasyIQ (widget 0001), week by week from the Monday of `from_datetime` to `to_datetime`."""
        if len(profiles) == 0: return []
        if not self.has_widget(AulaWidgetId.EASYIQ_WEEKPLAN): return []
        guardian_user_id = await self._get_guardian_user_id()
        institution_profile_codes = list(set(child.institution_code for child in profiles))
        call = _WidgetCall(AulaWidgetId.EASYIQ_WEEKPLAN, "EasyIQ", await self._get_token(AulaWidgetId.EASYIQ_WEEKPLAN))
        csrf_token = self._get_csrf_token()

        weeklyplans = list[AulaEasyiqWeeklyPlan]()
        from_datetime = from_datetime - timedelta(days=from_datetime.weekday())
        first = True
        while from_datetime < to_datetime:
            from_date = from_datetime.date()
            weekno = self._get_aula_week_formatted(from_date)
            for child in profiles:
                for inst_code in institution_profile_codes:
                    post_data: Dict[str, Any] = {
                        "sessionId": guardian_user_id,
                        "currentWeekNr": weekno,
                        "userProfile": "guardian",
                        "institutionFilter": [inst_code],
                        "childFilter": [child.user_id],
                    }

                    def send(token: AulaToken | None, inst_code: str = inst_code, post_data: Dict[str, Any] = post_data) -> Awaitable[HttpResponse]:
                        headers = self._get_easyiq_header(token, inst_code, csrf_token)
                        return self._session.post(self.easyiq_api + "/weekplaninfo", json=post_data, headers=headers)

                    response = await self._widget_send(call, send)
                    if response is None or response.status_code != HTTPStatus.OK:
                        self._widget_failed(call, response, first)
                        continue
                    plan = AulaEasyiqWeekplanParser.parse_events_as_weekly_plan(response.json(), child.first_name, str(child.user_id), from_date)
                    if plan.daily_plans:
                        weeklyplans.append(plan)
            from_datetime += timedelta(weeks=1)
            first = False
        _LOGGER.debug("Fetched easyiq weekplan: %s", len(weeklyplans))
        return weeklyplans

    async def get_newsletters(self, profiles: List[AulaChildProfile], from_datetime: datetime, to_datetime: datetime) -> List[AulaWeeklyNewsletter]:
        """The children's weekly newsletters in MinUddannelse (widget 0029), week by week from the Monday of `from_datetime` to `to_datetime`."""
        if len(profiles) == 0: return []
        if not self.has_widget(AulaWidgetId.MY_EDUCATION_WEEKLETTER): return []
        guardian_user_id = await self._get_guardian_user_id()
        child_userids_as_str_list = list(set(str(child.user_id) for child in profiles))
        call = _WidgetCall(AulaWidgetId.MY_EDUCATION_WEEKLETTER, "MinUddannelse", await self._get_token(AulaWidgetId.MY_EDUCATION_WEEKLETTER))
        requesturl = f"{self.min_uddannelse_api}/ugebrev?assuranceLevel=2&childFilter={",".join(child_userids_as_str_list)}&currentWeekNumber={{weekno}}&isMobileApp=false&placement=narrow&sessionUUID={guardian_user_id}&userProfile=guardian"

        newsletters = list[AulaWeeklyNewsletter]()
        from_datetime = from_datetime - timedelta(days=from_datetime.weekday())
        first = True
        while from_datetime < to_datetime:
            from_date = from_datetime.date()
            url = requesturl.format(weekno=self._get_aula_week_formatted(from_date))
            response = await self._widget_send(call, lambda token: self._session.get(url, headers=self._get_myeducation_header(token)))
            from_datetime += timedelta(weeks=1)
            if response is None or response.status_code != HTTPStatus.OK:
                self._widget_failed(call, response, first)
            else:
                newsletters.extend(AulaNewsletterParser.parse_response(response.json(), from_date))
            first = False
        _LOGGER.debug("Fetched newsletters: %s", len(newsletters))
        return newsletters

    async def _refresh_token(self, widgetid:AulaWidgetId, force: bool = False) -> AulaToken | None:
        """Fetch a new token for a widget, one fetch at a time; see `_refresh_token_locked`."""
        async with self._token_refresh_lock:
            return await self._refresh_token_locked(widgetid, force)

    async def _refresh_token_locked(self, widgetid:AulaWidgetId, force: bool = False) -> AulaToken | None:
        """Fetch a new token for a widget, unless one was fetched within 5 minutes; with the lock held.

        Its expiry is not checked: Aula hands out tokens already expired now and then, and only
        the widget knows whether it takes one.

        Returns:
            The new token; where none could be fetched, the token there was, unless `force`.

        Raises:
            AulaApiError: No token could be fetched, where `force`d; the token there was is
                forgotten.
            AulaCredentialError: The access token can no longer be renewed.
        """
        token = self._tokens.get(widgetid)
        current_time = datetime.now(timezone.utc)
        if not force and token is not None and current_time - token.timestamp < timedelta(minutes=5):
            _LOGGER.debug("Ignoring token refresh request to avoid refreshing too often for widget id: %s", widgetid)
            return token

        url = f"{self._apiurl}?method=aulaToken.getAulaToken&widgetId={widgetid}"
        try:
            response = await self._retry_on_401(await self._send("aulaToken.getAulaToken", lambda: self._session.get(url)), lambda: self._session.get(url))
            if response.status_code != HTTPStatus.OK:
                if force:
                    self._tokens.pop(widgetid, None)
                    raise AulaApiError(
                        f"Force-refresh failed for widget {widgetid}: aulaToken.getAulaToken returned "
                        f"HTTP {response.status_code} {response.reason}"
                    )
                _LOGGER.warning("Failed to refresh token for widget %s: HTTP %s %s",
                                widgetid, response.status_code, response.reason)
                return token
            data = response.json()["data"]
            if not isinstance(data, str):
                if force:
                    self._tokens.pop(widgetid, None)
                    raise AulaApiError(
                        f"Force-refresh failed for widget {widgetid}: aulaToken.getAulaToken returned "
                        f"non-string data (type={type(data).__name__}). This is an Aula server-side bug."
                    )
                _LOGGER.warning("Widget token response for %s contained non-string data (%s), skipping", widgetid, type(data).__name__)
                return token
            token = AulaToken(
                bearer_token = "Bearer " + data,
                timestamp = datetime.now(timezone.utc),
                expires_at = _decode_jwt_exp(data),
            )
            self._tokens[widgetid] = token
            if token.expires_at is not None:
                now = datetime.now(timezone.utc)
                ttl = (token.expires_at - now).total_seconds()
                if ttl <= 0:
                    _LOGGER.warning(
                        "Aula returned widget %s JWT with non-positive TTL (exp: %s, now: %s, age: %.0fs). "
                        "Widget call will likely fail. This is a known Aula server-side issue — "
                        "the integration cannot work around it.",
                        widgetid, token.expires_at.isoformat(), now.isoformat(), -ttl,
                    )
                else:
                    _LOGGER.debug(
                        "Widget %s token refreshed, JWT exp: %s (TTL: %.0fs)",
                        widgetid, token.expires_at.isoformat(), ttl,
                    )
            return token
        except (TimeoutError, aiohttp.ClientError, ConnectionError, ValueError, KeyError, TypeError) as e:
            # AulaCredentialError is left to propagate: only a new login helps.
            if force:
                self._tokens.pop(widgetid, None)
                raise AulaApiError(
                    f"Force-refresh failed for widget {widgetid}: aulaToken.getAulaToken raised "
                    f"{type(e).__name__}: {redact(e)}"
                ) from e
            _LOGGER.warning("Failed to refresh widget token for %s: %s: %s", widgetid, type(e).__name__, redact(e))
            return token

    async def _get_token(self, widgetid:AulaWidgetId) -> AulaToken | None:
        """A widget's token, the one there is while younger than TOKEN_EXPIRATION_TIME."""
        token = self._tokens.get(widgetid)
        if token is not None and datetime.now(timezone.utc) - token.timestamp < TOKEN_EXPIRATION_TIME:
            return token
        return await self._refresh_token(widgetid)

    def has_widget(self, widget_match: AulaWidgetId) -> bool:
        """Whether one of the institutions has the widget, as the login read them."""
        widgets = [] if self._login_result is None else self._login_result.widgets
        return any(widget.widget_id == widget_match for widget in widgets)

    def _get_aula_api(self) -> str:
        return self._session.api_base + str(self.api_version)

    def _get_user_agent(self) -> str:
        # Some of the widgets refuse a client that does not look like a browser.
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0"

    def _get_myeducation_header(self, token: AulaToken|None = None) -> Dict[str,str]:
        result: Dict[str, str] = {
            "user-agent": self._get_user_agent(),
            "accept": "application/json"
        }
        if token:
            result["authorization"] = token.bearer_token
        return result

    def _get_meebook_header(self, token: AulaToken|None = None) -> Dict[str,str]:
        result: Dict[str, str] = {
            "user-agent": self._get_user_agent(),
            "authority": "app.meebook.com",
            "accept": "application/json",
            "dnt": "1",
            "origin": "https://www.aula.dk",
            "referer": "https://www.aula.dk/",
            "sessionuuid": self._username,
            "x-version": "1.0",
        }
        if token:
            result["authorization"] = token.bearer_token
        return result

    def _get_easyiq_header(self, token: AulaToken|None, institution_profile_code: str, csrf_token: str | None) -> Dict[str,str]:
        result: Dict[str, str] = {
            "user-agent": self._get_user_agent(),
            "x-aula-institutionfilter": institution_profile_code,
            "x-aula-userprofile": "guardian",
            "accept": "application/json",
            "origin": "https://www.aula.dk",
            "referer": "https://www.aula.dk/",
            "authority": "api.easyiqcloud.dk",
            }
        if csrf_token:
            result["csrfp-token"] = csrf_token
        if token:
            result["authorization"] = token.bearer_token
        return result

    def _get_aula_header(self) -> Dict[str,str]:
        return {
            "user-agent": self._get_user_agent(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9,da;q=0.8",
            "Origin": "https://www.aula.dk",
            "Referer": "https://www.aula.dk/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
            "zone": "Europe/Copenhagen",
        }

    @staticmethod
    def flatten_children(profiles: Iterable[AulaProfile]) -> List[AulaChildProfile]:
        """The children of all the profiles."""
        return [child for profile in profiles for child in profile.children]

    @staticmethod
    def _get_aula_week_formatted(timestamp: datetime|date) -> str:
        return timestamp.strftime("%Y-W%V")

    async def _retry_on_401(self, response: HttpResponse, request_fn: Callable[[], Awaitable[HttpResponse]]) -> HttpResponse:
        """Where Aula refused the access token, renew it with the callback and send the request once more.

        A 401 Aula answers now and then for a token it takes is no reason for a new login.

        Raises:
            AulaCredentialError: The callback can no longer renew the access token.
            ConnectionError: The token could not be renewed for now, or the request failed again.
        """
        if response.status_code != HTTPStatus.UNAUTHORIZED:
            return response
        if self._token_refresh_callback is None:
            return response
        if not await self._token_refresh_callback():
            _LOGGER.warning("Access token refresh failed (transient), returning error without reauth")
            raise ConnectionError("Access token refresh failed — could not retry after 401")
        _LOGGER.debug("Got 401, retrying after access token refresh")
        try:
            retried = await request_fn()
        except (TimeoutError, aiohttp.ClientError):
            _LOGGER.debug("Retry after token refresh failed with network error")
            raise ConnectionError("Request failed after token refresh (network error)")
        if retried.status_code == HTTPStatus.UNAUTHORIZED:
            # The token was renewed just now: Aula refusing it is its own passing failure.
            _LOGGER.warning("API returned 401 even after successful token refresh — treating as transient")
            raise ConnectionError("API returned 401 after successful token refresh")
        return retried

    @staticmethod
    def _raise_error(response: HttpResponse) -> None:
        """Raise the error an answer of 400 or more says, with Aula's own message where it has one."""
        if response.ok: return
        message: str = f"{response.status_code} {response.reason or ''}"
        try:
            responsedata: dict[str, Any] = response.json()
            status: dict[str, Any] | None = responsedata.get("status")
            if isinstance(status, dict):
                msg: Any = status.get("message")
                if msg is not None:
                    message = str(msg)
        except (ValueError, AttributeError):
            pass
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            raise AulaCredentialError(message)
        if response.status_code == HTTPStatus.PAYMENT_REQUIRED: raise PermissionError(message)
        if response.status_code == HTTPStatus.FORBIDDEN: raise PermissionError(message)
        raise AulaApiError(message)
