"""Aula read with tokens that are kept fresh: the API client and the login client together."""

from collections.abc import AsyncGenerator, Awaitable, Collection, Sequence
from contextlib import asynccontextmanager
from functools import partial
from typing import Any, Callable, List, cast
import asyncio
import datetime
import json
import logging
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

import aiohttp

from .api.const import API_VERSION
from .api.models.constants import AulaWidgetId
from .api.module import (
    AulaBirthdayEvent,
    AulaPresenceConfiguration,
    AulaProfilePicture,
    AulaPresenceStatus,
    AulaSickReportCheck,
    AulaSickReportRoute,
    AulaClosedDay,
    AulaOpeningDay,
    AulaPosts,
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
from .api.aula_errors import AulaApiError, AulaCredentialError, MethodRefusedError, NoSickReportRouteError, SickReportFinalError
from .catalog_read import FOLLOWED, NO_VALUES, UNKNOWN_VALUES, Account, plan, readable, then
from .methods import Kind, alike, known
from .pseudonym import pseudonymised, shapes
from . import read_marks
from .read_marks import WATCHED, ReadMark, compare
from .login import AulaLoginClient
from .redact import redact
from .login.exceptions import NetworkError, TokenExpiredError
from .tabulex import PORTAL as TABULEX_PORTAL, TabulexClient, TabulexError, match, named
from .widget_probe import NOT_FOLLOWED, WidgetProbe, WidgetProbeReport, probe, probe_session

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
        self._widget_probe: WidgetProbeReport | None = None
        self._tabulex_portal = TABULEX_PORTAL
        self._tabulex_session: Callable[[], aiohttp.ClientSession] = probe_session
        self._tabulex_not_followed: tuple[str, ...] = NOT_FOLLOWED
        self._tabulex_secrets: set[str] = set()
        self._read_marks: list[ReadMark] = []

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
        reads. Then each other method of the catalog that only reads is asked once about the
        account's children, institutions and groups, and the first items of a list it answers
        with, such as posts and albums, one by one. Last, each answer that holds marks of what the
        user has seen - the news feed, the message threads and the notifications - is asked again,
        `read_marks.RECHECK_AFTER` after it was first at the least, to tell whether reading moved
        a mark; `responses` holds what it told.

        Returns:
            What could not be read, each with its error, and each method of the catalog that only
            reads and was not asked, with why.

        Raises:
            AulaCredentialError: The tokens can no longer be renewed; only a new login helps.
        """
        failed: List[str] = []
        self._read_marks = []

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
        if self._proxy.has_tabulex():
            await read("Tabulex", self._read_tabulex)
        await self._read_catalog(read, profiles, children, start, end, failed)
        await self._read_marks_again(read, children)
        return failed

    async def _read_marks_again(
        self, read: Callable[[str, Callable[[], Awaitable[Any]]], Awaitable[Any]], children: List[AulaChildProfile]
    ) -> None:
        """Ask again each method whose answer holds marks of what the user has seen, and keep what changed."""
        recorder = self._proxy.recorder
        for watched in WATCHED:
            first = next((e for e in reversed(recorder.exchanges()) if e.endpoint == watched.method and not e.failed), None)
            if first is None:
                continue
            wait = (first.at + read_marks.RECHECK_AFTER - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
            if wait > 0:
                await asyncio.sleep(wait)
            match watched.method:
                case "posts.getAllPosts":
                    params = [(name, value) for name, value in parse_qsl(urlsplit(first.url).query) if name != "method"]
                    again: Callable[[], Awaitable[Any]] = partial(self._ask, watched.method, params)
                case "messaging.getThreads":
                    again = self.get_message_threads
                case _:
                    again = partial(self.get_notifications, children)
            await read(f"{watched.method} again", again)
            second = next(
                (e for e in reversed(recorder.exchanges()) if e.endpoint == watched.method and e is not first and e.at >= first.at and not e.failed), None
            )
            if second is not None:
                self._read_marks.append(compare(watched, first.response, second.response, (second.at - first.at).total_seconds()))

    async def _read_catalog(
        self,
        read: Callable[[str, Callable[[], Awaitable[Any]]], Awaitable[Any]],
        profiles: Sequence[AulaProfile],
        children: Sequence[AulaChildProfile],
        start: datetime.datetime,
        end: datetime.datetime,
        failed: List[str],
    ) -> None:
        """Ask once each method of the catalog that only reads, not asked already, and say why of any left."""
        account = Account(
            children=sorted({child.id for child in children}),
            own=sorted({own.id for profile in profiles for own in profile.institution_profiles}),
            profiles=sorted(
                {*(own.id for profile in profiles for own in profile.institution_profiles), *(child.id for child in children)}
            ),
            institutions=sorted({child.institution_code for child in children}),
            groups=sorted({child.main_group.id for child in children if child.main_group.id}),
            start=start.date(),
            end=end.date(),
        )
        before = {exchange.endpoint for exchange in self._proxy.recorder.exchanges()}
        queue = [(method, params) for method, params in plan(account) if method not in before]
        while queue:
            method, params = queue.pop(0)
            data = await read(method, partial(self._ask, method, params))
            if data is not None:
                queue[0:0] = then(method, data, account)
        asked = {exchange.endpoint for exchange in self._proxy.recorder.exchanges()}
        for name in readable():
            if name not in asked:
                failed.append(f"{name}: not asked, as {NO_VALUES.get(name) or _not_asked(name)}")

    async def _ask(self, method: str, params: Sequence[tuple[str, str]]) -> Any:
        """Ask `method`, which only reads and is asked with GET, and give the data Aula answered with.

        Raises:
            AulaApiError: Aula answered with an error, or with no data.
        """
        _refuse(method, dict(params), None)
        await self._ensure_valid_token()
        answer = await self._proxy.custom_api_call(f"?{urlencode([*params, ('method', method)])}", None)
        status = cast(dict[str, Any], answer).get("status") if isinstance(answer, dict) else None
        code = cast(dict[str, Any], status).get("code") if isinstance(status, dict) else None
        if code != 0:
            message = cast(dict[str, Any], status).get("message") if isinstance(status, dict) else None
            raise AulaApiError(f"Aula answered code {code}: {message or 'no message'}")
        return cast(dict[str, Any], answer).get("data")

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
        secrets = [self._mitid_username, self._access_token, self._refresh_token, *self._proxy.secrets(), *self._tabulex_secrets]
        answers = pseudonymised(self._proxy.recorder.exchanges(), key, secrets, reveal)
        return [answer for answer in answers if answer["endpoint"] == method][-1]

    def responses(self, key: bytes) -> dict[str, Any]:
        """The newest answers and failures Aula gave this client, with who someone is replaced.

        One `key` replaces a value by the same other value each time; see `aula_connect.pseudonym`.
        The MitID username and every token the client holds are hidden wherever they are. The
        answers are listed with Aula's API version and the type at each place of each kind.
        """
        secrets = [self._mitid_username, self._access_token, self._refresh_token, *self._proxy.secrets(), *self._tabulex_secrets]
        exchanges = pseudonymised(self._proxy.recorder.exchanges(), key, secrets)
        kinds: dict[str, dict[str, set[str]]] = {}
        for exchange in exchanges:
            found = kinds.setdefault(f"{exchange['method']} {exchange['endpoint']}", {})
            for at, types in shapes(exchange["response"]).items():
                found.setdefault(at, set()).update(types)
        return {
            "aula_api_version": self._proxy.api_version,
            "read_marks": [mark.as_dict() for mark in self._read_marks],
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

    async def report_sick(self, child: AulaChildProfile) -> AulaSickReportRoute:
        """Report the child sick today, along its route, once; the route it was reported along.

        Through Aula's presence module, see `AulaProxyClient.report_sick`; or through IST's
        Tabulex, the child found there by its name, where the report cannot be taken back.

        Raises:
            NoSickReportRouteError: No way is known to report the child sick.
            TabulexError: Tabulex could not be logged in to, knows no child of the name, or
                refused or failed the report; where no answer came, it may or may not have
                registered it.
        """
        await self._ensure_valid_token()
        if await self._proxy.get_sick_report_route(child) is AulaSickReportRoute.TABULEX:
            async with self.tabulex() as tabulex:
                found = match(child, await tabulex.children())
                if found is None:
                    raise TabulexError("Tabulex knows no child of that name at the institution Aula has it at")
                await tabulex.report_sick_today(found)
            return AulaSickReportRoute.TABULEX
        await self._proxy.report_sick(child)
        return AulaSickReportRoute.AULA

    async def undo_sick(self, child: AulaChildProfile) -> None:
        """Take back today's report that the child is sick; see `AulaProxyClient.undo_sick`.

        Raises:
            SickReportFinalError: The child is reported sick through Tabulex, which takes no
                report back.
        """
        await self._ensure_valid_token()
        if await self._proxy.get_sick_report_route(child) is AulaSickReportRoute.TABULEX:
            raise SickReportFinalError("IST Tabulex")
        await self._proxy.undo_sick(child)

    async def check_sick_report(self, child: AulaChildProfile) -> AulaSickReportCheck:
        """What reporting the child sick would do, found without sending anything.

        Along Aula's presence module, the child's presence today is read; through IST's Tabulex,
        the portal is logged in to, the child looked for by its name, and its absence today read.

        Raises:
            TabulexError: Tabulex could not be logged in to, or refused or failed a read.
        """
        await self._ensure_valid_token()
        route = await self._proxy.get_sick_report_route(child)
        if route is AulaSickReportRoute.TABULEX:
            async with self.tabulex() as tabulex:
                children = await tabulex.children()
                found = match(child, children)
                day = None if found is None else await tabulex.today(found)
            request = None if found is None else "PUT /api/Fravaer/MeldSygIdag/"
            same = True if found is not None else (False if named(child, children) else None)
            return AulaSickReportCheck(route, found is not None, None if day is None else day.sick, request, same)
        if route is AulaSickReportRoute.AULA:
            overview = await self._proxy.get_child_overview(child)
            sick = None if overview is None else overview.status == AulaPresenceStatus.SICK
            return AulaSickReportCheck(route, True, sick, "POST presence.updateStatusByInstitutionProfileIds", True)
        return AulaSickReportCheck(route, False, None, None)

    def use_tabulex(
        self, portal: str, session: Callable[[], aiohttp.ClientSession], not_followed: Sequence[str] = NOT_FOLLOWED
    ) -> None:
        """Reach Tabulex's portal at `portal`, on sessions `session` makes, as a test does a simulated one."""
        self._tabulex_portal, self._tabulex_session, self._tabulex_not_followed = portal, session, tuple(not_followed)

    @asynccontextmanager
    async def tabulex(self) -> AsyncGenerator[TabulexClient]:
        """IST's Tabulex parent portal, logged in to through the login's widget with a new widget token, while the context lasts.

        It runs on a session of its own, closed after it: Tabulex's cookies are not Aula's.

        Raises:
            NoSickReportRouteError: The login has no widget into Tabulex.
            TabulexError: The login to Tabulex did not reach the portal.
        """
        await self._ensure_valid_token()
        forms = [form for form in await self._proxy.sso_login_forms() if AulaProxyClient.is_tabulex(form[1], form[2])]
        if not forms:
            raise NoSickReportRouteError("The login has no widget into Tabulex")
        _, _, url, fields = forms[0]
        async with self._tabulex_session() as session:
            client = TabulexClient(session, self._tabulex_portal, self._proxy.recorder)
            try:
                await client.log_in(url, fields, self._tabulex_not_followed)
                yield client
            finally:
                self._tabulex_secrets.update(client.secrets())

    async def _read_tabulex(self) -> None:
        async with self.tabulex() as tabulex:
            for child in await tabulex.children():
                await tabulex.today(child)
                await tabulex.tomorrow(child)
                await tabulex.school_days(child)

    async def get_posts(self, profiles: List[AulaProfile], limit: int = 20) -> AulaPosts:
        """The newest posts of the news feed, `limit` of them, and when the guardian last saw them."""
        await self._ensure_valid_token()
        return await self._proxy.get_posts(profiles, limit)

    async def get_closed_days(self, children: List[AulaChildProfile]) -> List[AulaClosedDay]:
        """The days the children's institutions are closed, such as holidays."""
        await self._ensure_valid_token()
        return await self._proxy.get_closed_days(children)

    async def get_opening_hours(
        self, children: List[AulaChildProfile], start: datetime.date, end: datetime.date
    ) -> List[AulaOpeningDay]:
        """The children's institutions' hours from `start` to `end`, day by day."""
        await self._ensure_valid_token()
        return await self._proxy.get_opening_hours(children, start, end)

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

    async def probe_widgets(
        self,
        session: aiohttp.ClientSession | None = None,
        reads: Sequence[str] = (),
        not_followed: Sequence[str] = NOT_FOLLOWED,
    ) -> WidgetProbeReport:
        """Follow, once, how each widget that logs in to a service of its own logs the guardian in, and read what the service loads and names.

        Each widget is opened as Aula's portal opens it on a desktop, with a new widget token, its
        login chain followed as a browser follows it, and its service's scripts and the
        addresses they name read; see `aula_connect.widget_probe.probe`. It only reads: nothing
        is posted but the widget's form and the forms the chain's pages submit by themselves,
        and no address whose path names a change is read unasked. The report tells no value of
        a token, a cookie or a field, a JSON answer only by its shape and pseudonymised, and is
        kept as `widget_probe`.

        Args:
            session: The session each chain is followed on, with cookies of its own, not
                Aula's, sent back as they were set; a new one for each widget where None.
            reads: Addresses, or paths resolved against the page each chain ends at, read too.
            not_followed: The domains of logins never followed into.
        """
        await self._ensure_valid_token()
        widgets: list[WidgetProbe] = []
        for widget_id, supplier, url, fields in await self._proxy.sso_login_forms():
            if session is None:
                async with probe_session() as own:
                    widgets.append(await probe(own, widget_id, supplier, url, fields, reads, not_followed))
            else:
                session.cookie_jar.clear()
                widgets.append(await probe(session, widget_id, supplier, url, fields, reads, not_followed))
        report = WidgetProbeReport(tuple(widgets))
        self._widget_probe = report
        return report

    @property
    def widget_probe(self) -> WidgetProbeReport | None:
        """The report of the newest probe of the widgets' services; None before one."""
        return self._widget_probe

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


def _not_asked(name: str) -> str:
    """Why `name`, a method of the catalog that only reads, was not asked."""
    return "there was nothing to ask it about" if name in FOLLOWED else UNKNOWN_VALUES


_NEVER = {
    Kind.MESSAGES: "it gets the text of messages, which may be marked sensitive",
    Kind.SECURE_DOCUMENTS: "it gets secure documents, which may be marked sensitive",
    Kind.TOKEN: "it hands out a token, which is a credential",
    Kind.WRITE: "it changes Aula",
    Kind.PERSONAL: "it gets answers about a person, which may be sensitive",
    Kind.STAFF: "it is for the institution's staff, and Aula refuses a guardian",
}
