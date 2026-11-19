"""Aula read with tokens that are kept fresh: the API client and the login client together."""

from collections.abc import Awaitable, Collection, Sequence
from functools import partial
from typing import Any, Callable, List
import asyncio
import datetime
import json
import logging
import re
import time
from urllib.parse import urlencode

import aiohttp

from .api.const import API_VERSION
from .api.models.constants import AulaWidgetId
from .api.module import (
    AulaBirthdayEvent,
    AulaPresenceConfiguration,
    AulaProfilePicture,
    AulaSickReportRoute,
    AulaVacation,
    AulaVacationDay,
    AulaVacationRequest,
    AulaVacationRequestDetail,
    AulaCalendarEvent,
    AulaEventDetail,
    AulaDailyOverview,
    AulaEasyiqWeeklyPlan,
    AulaInstitutionProfile,
    AulaMessage,
    AulaLoginData,
    AulaMessageThread,
    AulaProfile,
    AulaProxyClient,
    AulaWeeklyNewsletter,
    AulaWeeklyPlan,
    AulaChildProfile,
    AULA_NOTIFICATION_TYPES,
)
from .anomaly import Anomaly
from .api.aula_errors import AulaCredentialError, MethodRefusedError
from .methods import Kind, alike, known
from .pseudonym import pseudonymised, shapes
from .login import AulaLoginClient
from .redact import redact
from .login.exceptions import NetworkError, TokenExpiredError
from .tabulex_probe import TABULEX_DOMAINS, TABULEX_PORTAL, TabulexProbeReport, follow

_LOGGER = logging.getLogger(__name__)

YEAR = datetime.timedelta(days=366)
"""How far ahead the next birthday is looked for when everything is read."""

BIRTHDAY_PERIOD = datetime.timedelta(days=28)
"""The longest period one request asks Aula's birthdays for: Aula answers none for a year at once."""

TOKEN_REFRESH_BUFFER_SECONDS = 300
"""Refresh tokens 5 minutes before expiry."""


class AulaClient:
    """Aula's API, read with an access token renewed before it expires, and again where Aula refuses it.

    Raises from every read, besides what the API client raises:
        AulaCredentialError: The tokens can no longer be renewed; only a new login helps.
        ConnectionError: The tokens could not be renewed for now.
    """

    aula_version: int = int(API_VERSION)
    _proxy: AulaProxyClient

    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_token: str,
        refresh_token: str,
        expires_at: float,
        mitid_username: str,
        login_client: AulaLoginClient,
        token_update_callback: Callable[[str, str, float], None] | None = None,
    ):
        """Read Aula on `session` with the tokens a login gave.

        Args:
            expires_at: When the access token expires, in seconds since the epoch.
            login_client: The login client that renews the tokens.
            token_update_callback: Called with the access token, the refresh token and their
                expiry each time they are renewed, to keep them.
        """
        self._access_token: str = access_token
        self._refresh_token: str = refresh_token
        self._expires_at: float = expires_at
        self._mitid_username = mitid_username
        self._login_client = login_client
        self._token_update_callback = token_update_callback
        self._token_lock = asyncio.Lock()
        self._proxy = AulaProxyClient(session, access_token)
        self._proxy.set_token_refresh_callback(self._force_refresh_access_token)
        self._tabulex_probe: TabulexProbeReport | None = None

    @property
    def api(self) -> AulaProxyClient:
        """The client of Aula's API this client reads through."""
        return self._proxy

    async def connection_check(self) -> None:
        """Log in to Aula's API, and take the version it is at.

        Raises:
            AulaCredentialError: Aula refused the access token.
            ConnectionRefusedError: Aula's API could not be found.
        """
        await self._ensure_valid_token()
        await self._proxy.login()
        self.aula_version = self._proxy.api_version

    def has_widget(self, widgetid: AulaWidgetId) -> bool:
        """Whether one of the institutions has the widget, as the login read them."""
        return self._proxy.has_widget(widgetid)

    async def login(self) -> AulaLoginData:
        """The user's profiles and the institutions' widgets; see `AulaProxyClient.login`."""
        await self._ensure_valid_token()
        return await self._proxy.login()

    async def _force_refresh_access_token(self) -> bool:
        """Renew the access token whatever its expiry, and answer whether it was renewed.

        Raises:
            AulaCredentialError: The tokens can no longer be renewed; only a new login helps.
        """
        self._expires_at = 0
        try:
            await self._ensure_valid_token()
            return True
        except AulaCredentialError:
            raise
        except Exception:
            _LOGGER.debug("Forced token refresh failed (transient)", exc_info=True)
            return False

    async def _ensure_valid_token(self) -> None:
        """Renew the access token where it expires within TOKEN_REFRESH_BUFFER_SECONDS, once for callers that ask at the same time.

        Raises:
            AulaCredentialError: The tokens can no longer be renewed; only a new login helps.
            ConnectionError: The tokens could not be renewed for now.
        """
        if time.time() < self._expires_at - TOKEN_REFRESH_BUFFER_SECONDS:
            return

        async with self._token_lock:
            # Another caller may have renewed it while this one waited.
            if time.time() < self._expires_at - TOKEN_REFRESH_BUFFER_SECONDS:
                return

            if not self._refresh_token:
                raise AulaCredentialError("No refresh token available, re-authentication required")

            _LOGGER.debug("Access token expired or expiring soon, attempting refresh")
            self._login_client.tokens = {
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
            }

            try:
                success = await self._login_client.renew_access_token()
            except TokenExpiredError as err:
                raise AulaCredentialError(
                    "Refresh token expired, re-authentication required"
                ) from err
            except (NetworkError, OSError) as err:
                _LOGGER.warning("Network error during token refresh: %s", redact(err))
                raise ConnectionError(f"Network error during token refresh: {redact(err)}") from None

            if not success:
                # An answer the renewal does not know is no refusal of the refresh token.
                _LOGGER.warning("Token refresh returned False — treating as transient failure")
                raise ConnectionError("Token refresh failed — server returned an unexpected response")

            tokens = self._login_client.tokens or {}
            new_access = str(tokens["access_token"])
            new_refresh = str(tokens.get("refresh_token", self._refresh_token))
            new_expires = float(tokens.get("expires_at", time.time() + 3600))

            self._access_token = new_access
            self._refresh_token = new_refresh
            self._expires_at = new_expires
            self._proxy.update_token(new_access)

            _LOGGER.debug("Token refreshed successfully, expires at %s", new_expires)

            if self._token_update_callback:
                self._token_update_callback(new_access, new_refresh, new_expires)

    async def get_birthday_events(
        self,
        profiles: List[AulaChildProfile],
        start_datetime: datetime.datetime,
        end_datetime: datetime.datetime,
    ) -> List[AulaBirthdayEvent]:
        """The birthdays in the period that Aula ties to one of the children, or to none."""
        await self._ensure_valid_token()
        return await self._proxy.get_birthday_events(profiles, start_datetime, end_datetime)

    async def get_event(self, event_id: int) -> AulaEventDetail | None:
        """The event `event_id` as Aula tells it alone; None where Aula answered with no content."""
        await self._ensure_valid_token()
        return await self._proxy.get_event(event_id)

    async def get_messages(self, thread: AulaMessageThread) -> List[AulaMessage]:
        """The newest page of the messages of a thread not marked sensitive."""
        await self._ensure_valid_token()
        return await self._proxy.get_messages(thread)

    async def read_everything(self, start: datetime.datetime, end: datetime.datetime) -> List[str]:
        """Read once all this client reads from Aula, so that its recorder holds each answer.

        `start` and `end` bound the calendar events, each but a lesson read by its id too, the
        birthdays, weekly plans and newsletters, and
        the next birthday from `start` is looked for too, four weeks a request, a year at most; the messages of every thread of the
        newest page are read as well, but for those Aula marks sensitive, which the client never
        reads.

        Returns:
            What could not be read, each with its error.

        Raises:
            AulaCredentialError: The tokens can no longer be renewed; only a new login helps.
        """
        failed: List[str] = []

        async def read[T](what: str, call: Callable[[], Awaitable[T]]) -> T | None:
            try:
                return await call()
            except AulaCredentialError:
                raise
            except Exception as error:
                failed.append(f"{what}: {redact(error)}")
                return None

        login = await read("profiles", self.login)
        if login is None:
            return failed
        profiles = login.profiles
        children = AulaProxyClient.flatten_children(profiles)
        institutions = {child.institution_profile.id: child.institution_profile for child in children}
        await read("daily overviews", partial(self.get_daily_overviews, profiles))
        found = await read("message threads", self.get_message_threads) or []
        for thread in [thread for thread in found if not thread.sensitive]:
            await read("messages", partial(self.get_messages, thread))
        await read("notifications", partial(self.get_notifications, children))
        for institution in institutions.values():
            events = await read("calendar events", partial(self.get_calendar_events, [institution], start, end)) or []
            for event in [event for event in events if event.type != "lesson"]:
                await read("event", partial(self.get_event, event.id))
        await read("birthdays", partial(self.get_birthday_events, children, start, end))
        for period in range(0, YEAR.days, BIRTHDAY_PERIOD.days):
            begin = start + datetime.timedelta(days=period)
            end_of_period = min(begin + BIRTHDAY_PERIOD, start + YEAR)
            if await read("next birthday", partial(self.get_birthday_events, children, begin, end_of_period)):
                break
        if self.has_widget(AulaWidgetId.WEEKPLAN_PARENTS):
            await read("weekly plans", partial(self.get_weekly_plans, children, start, end))
        if self.has_widget(AulaWidgetId.EASYIQ_WEEKPLAN):
            await read("EasyIQ weekly plans", partial(self.get_easyiq_weekly_plans, children, start, end))
        if self.has_widget(AulaWidgetId.MY_EDUCATION_WEEKLETTER):
            await read("newsletters", partial(self.get_newsletters, children, start, end))
        return failed

    def anomalies(self, since: datetime.datetime | None = None) -> tuple[Anomaly, ...]:
        """What Aula sent that this client does not know or could not read, the latest first.

        Each is given once - an area, an answer or a version of Aula's API the client was not made
        for, none telling any of Aula's data - and only what was last met at or after `since`
        where given. A version Aula's API is at is met again at each login, for as long as it
        lasts. The client keeps them for as long as it lives, and is read on the event loop it
        runs on.

        Raises:
            ValueError: `since` has no time zone.
        """
        return self._proxy.anomalies(since)

    async def read(
        self,
        method: str,
        params: dict[str, str],
        key: bytes,
        reveal: bool | Collection[str] = False,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ask Aula's API `method` with `params`, and give its answer as `responses` gives one.

        A method `aula_connect.methods` knows is asked as it is known to be: with GET, or with POST
        and `body` as JSON; one it does not know is asked where it is named as one that gets,
        "<area>.get<What>" or "<area>.find<What>". Never asked are a method that changes Aula, nor
        what may be marked sensitive - the text of messages and secure documents. `reveal` keeps
        the values under the keys it names as Aula sent them, or all the answer where it is True;
        the MitID username and every token are hidden all the same.

        Raises:
            MethodRefusedError: The method is never asked, in any case, it is asked with the
                other verb, or `params` or `body` names a method or a token.
        """
        _refuse(method, params, body)
        await self._ensure_valid_token()
        await self._proxy.custom_api_call(
            f"?{urlencode({**params, 'method': method})}", None if body is None else json.dumps(body)
        )
        secrets = [self._mitid_username, self._access_token, self._refresh_token, *self._proxy.secrets()]
        answers = pseudonymised(self._proxy.recorder.exchanges(), key, secrets, reveal)
        return [answer for answer in answers if answer["endpoint"] == method][-1]

    def responses(self, key: bytes) -> dict[str, Any]:
        """The newest answers and failures Aula gave this client, with who someone is replaced.

        One `key` replaces a value by the same other value each time; see `aula_connect.pseudonym`.
        The MitID username and every token the client holds are hidden wherever they are. The
        answers are listed with Aula's API version and the type at each place of each kind.
        """
        secrets = [self._mitid_username, self._access_token, self._refresh_token, *self._proxy.secrets()]
        exchanges = pseudonymised(self._proxy.recorder.exchanges(), key, secrets)
        kinds: dict[str, dict[str, set[str]]] = {}
        for exchange in exchanges:
            found = kinds.setdefault(f"{exchange['method']} {exchange['endpoint']}", {})
            for at, types in shapes(exchange["response"]).items():
                found.setdefault(at, set()).update(types)
        return {
            "aula_api_version": self._proxy.api_version,
            "exchanges": exchanges,
            "shapes": {
                kind: {at: sorted(types) for at, types in sorted(found.items())}
                for kind, found in sorted(kinds.items())
            },
        }

    async def get_daily_overviews(
        self, profiles: List[AulaProfile]
    ) -> List[AulaDailyOverview]:
        """Today's presence of the profiles' children."""
        await self._ensure_valid_token()
        return await self._proxy.get_daily_overviews(profiles)

    async def get_calendar_events(
        self,
        profiles: List[AulaInstitutionProfile],
        start_datetime: datetime.datetime,
        end_datetime: datetime.datetime,
    ) -> List[AulaCalendarEvent]:
        """The calendar events of the institution profiles in the period."""
        await self._ensure_valid_token()
        return await self._proxy.get_calendar_events(profiles, start_datetime, end_datetime)

    async def get_message_threads(self) -> List[AulaMessageThread]:
        """The newest page of the user's message threads."""
        await self._ensure_valid_token()
        return await self._proxy.get_message_threads()

    async def get_notifications(
        self, profiles: List[AulaChildProfile]
    ) -> List[AULA_NOTIFICATION_TYPES]:
        """The user's notifications about the children."""
        await self._ensure_valid_token()
        return await self._proxy.get_notifications(profiles)

    async def get_weekly_plans(
        self,
        profiles: List[AulaChildProfile],
        start_datetime: datetime.datetime,
        end_datetime: datetime.datetime,
    ) -> List[AulaWeeklyPlan]:
        """The children's weekly plans in Meebook in the period."""
        await self._ensure_valid_token()
        return await self._proxy.get_weekly_plans(profiles, start_datetime, end_datetime)

    async def get_easyiq_weekly_plans(
        self,
        profiles: List[AulaChildProfile],
        start_datetime: datetime.datetime,
        end_datetime: datetime.datetime,
    ) -> List[AulaEasyiqWeeklyPlan]:
        """The children's weekly plans in EasyIQ in the period."""
        await self._ensure_valid_token()
        return await self._proxy.get_easyiq_weekly_plans(
            profiles, start_datetime, end_datetime
        )

    async def get_newsletters(
        self,
        profiles: List[AulaChildProfile],
        start_datetime: datetime.datetime,
        end_datetime: datetime.datetime,
    ) -> List[AulaWeeklyNewsletter]:
        """The children's weekly newsletters in MinUddannelse in the period."""
        await self._ensure_valid_token()
        return await self._proxy.get_newsletters(profiles, start_datetime, end_datetime)


    async def get_presence_configurations(self, children: List[AulaChildProfile]) -> List[AulaPresenceConfiguration]:
        """What the children's guardian may see and do in the presence module, for each child Aula tells it of."""
        await self._ensure_valid_token()
        return await self._proxy.get_presence_configurations(children)

    async def get_sick_report_route(self, child: AulaChildProfile) -> AulaSickReportRoute:
        """Where the child is reported sick; see `AulaProxyClient.get_sick_report_route`."""
        await self._ensure_valid_token()
        return await self._proxy.get_sick_report_route(child)

    async def report_sick(self, child: AulaChildProfile) -> None:
        """Report the child sick today; see `AulaProxyClient.report_sick`."""
        await self._ensure_valid_token()
        await self._proxy.report_sick(child)

    async def undo_sick(self, child: AulaChildProfile) -> None:
        """Take back today's report that the child is sick; see `AulaProxyClient.undo_sick`."""
        await self._ensure_valid_token()
        await self._proxy.undo_sick(child)

    async def get_vacations(self, children: List[AulaChildProfile]) -> List[AulaVacation]:
        """The vacations and time off registered for the children."""
        await self._ensure_valid_token()
        return await self._proxy.get_vacations(children)

    async def add_vacation(self, children: List[AulaChildProfile], start: datetime.date, end: datetime.date, comment: str = "") -> None:
        """Register a vacation for the children, `start` to `end` included; see `AulaProxyClient.add_vacation`."""
        await self._ensure_valid_token()
        await self._proxy.add_vacation(children, start, end, comment)

    async def delete_vacation(self, vacation_id: int) -> None:
        """Delete a vacation of one of the login's children; see `AulaProxyClient.delete_vacation`."""
        await self._ensure_valid_token()
        await self._proxy.delete_vacation(vacation_id)

    async def get_vacation_requests(self, children: List[AulaChildProfile]) -> List[AulaVacationRequest]:
        """The institutions' requests to say whether the children come, answered or not."""
        await self._ensure_valid_token()
        return await self._proxy.get_vacation_requests(children)

    async def get_vacation_request(self, response_id: int) -> AulaVacationRequestDetail | None:
        """The vacation request `response_id` with its answer as it stands; None where Aula answered with no content."""
        await self._ensure_valid_token()
        return await self._proxy.get_vacation_request(response_id)

    async def answer_vacation_request(self, response_id: int, days: Sequence[AulaVacationDay], comment: str = "") -> None:
        """Answer a vacation request day by day; see `AulaProxyClient.answer_vacation_request`."""
        await self._ensure_valid_token()
        await self._proxy.answer_vacation_request(response_id, days, comment)

    async def threads_about(self, child: AulaChildProfile) -> List[AulaMessageThread]:
        """The threads of the newest page that are about the child, the one with the newest message first."""
        await self._ensure_valid_token()
        return await self._proxy.threads_about(child)

    async def reply(self, thread_id: int, text: str) -> None:
        """Send plain `text` to everyone still in a thread; see `AulaProxyClient.reply`."""
        await self._ensure_valid_token()
        await self._proxy.reply(thread_id, text)

    async def get_profile_picture(self, child: AulaChildProfile) -> AulaProfilePicture | None:
        """The child's profile picture as Aula tells it now, its address valid for about an hour; None where it has none."""
        await self._ensure_valid_token()
        return await self._proxy.get_profile_picture(child)

    async def probe_tabulex(
        self,
        session: aiohttp.ClientSession | None = None,
        domains: tuple[str, ...] = TABULEX_DOMAINS,
        portal: str = TABULEX_PORTAL,
    ) -> TabulexProbeReport:
        """Follow, once, how IST's Tabulex logs the guardian in from Aula, and read what its parent portal loads.

        The login's Tabulex widget is opened as Aula's portal opens it on a desktop, with a new
        widget token, and the login chain followed on `domains` only; see
        `aula_connect.tabulex_probe.follow`. It only reads: nothing is posted but the widget's
        form and the forms the chain's pages submit by themselves. The report tells no value of
        a token, a cookie or a field, and is kept as `tabulex_probe`.

        Args:
            session: The session the chain is followed on, with cookies of its own, not
                Aula's; a new one where None.

        Raises:
            NoTabulexWidgetError: The login has no widget of IST's that signs in to Tabulex.
            AulaApiError: No widget token could be fetched.
        """
        await self._ensure_valid_token()
        widget_id, url, fields = await self._proxy.tabulex_login_form()
        if session is None:
            async with aiohttp.ClientSession() as own:
                report = await follow(own, widget_id, url, fields, domains, portal)
        else:
            report = await follow(session, widget_id, url, fields, domains, portal)
        self._tabulex_probe = report
        return report

    @property
    def tabulex_probe(self) -> TabulexProbeReport | None:
        """The report of the newest probe of Tabulex's login; None before one."""
        return self._tabulex_probe

def _refuse(method: str, params: dict[str, str], body: dict[str, Any] | None) -> None:
    """Raise MethodRefusedError where `method` is not to be asked with `params` and `body`."""
    if (never := alike(method)) is not None and not never.readable:
        raise MethodRefusedError(f"{method!r} is never asked: {_NEVER[never.kind]}")
    if (found := known(method)) is not None:
        if (found.verb == "POST") != (body is not None):
            raise MethodRefusedError(f"{method!r} is asked with {found.verb}, {'with' if body is None else 'without'} a body")
    elif not re.fullmatch(r"[a-z]+\.(get|find)[A-Z][A-Za-z]*", method) or re.search("messag|secure", method, re.IGNORECASE):
        raise MethodRefusedError(f"{method!r} is not known, nor named as a method that only gets")
    if {"method", "access_token"} & {name.lower() for name in [*params, *(body or {})]}:
        raise MethodRefusedError("params and body must not name a method or a token")


_NEVER = {
    Kind.MESSAGES: "it gets the text of messages, which may be marked sensitive",
    Kind.SECURE_DOCUMENTS: "it gets secure documents, which may be marked sensitive",
    Kind.TOKEN: "it hands out a token, which is a credential",
    Kind.WRITE: "it changes Aula",
}
