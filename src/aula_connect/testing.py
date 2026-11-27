"""A simulated Aula, for tests: its login chain - from Aula's OAuth through UniLogin, NemLog-in
and MitID back to Aula's tokens - and its API, each answered as the real one is.

Each step checks what the real one depends on - the cookies set by the steps before it, the
verification token, the SAML responses handed on, the OAuth state and the PKCE verifier - so a
test of a login exercises how the client carries its session, not only its requests. MitID is
`mitid_connect.testing.SimulatedMitID`.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import itertools
import json
import re
import secrets
import socket
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self, cast
from urllib.parse import quote, urlencode

import aiohttp
from aiohttp import web
from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.test_utils import TestServer
from mitid_connect.testing import Network, SimulatedMitID, User

from .api.aula_proxy_client import AulaProxyClient
from .methods import known
from .login import AulaLoginClient
from .widget_probe import probe_session

if TYPE_CHECKING:
    from .client import AulaClient

APP_REDIRECT_URI = "https://app-private.aula.dk"
"""Where Aula sends the app back to, with the code; it is never requested."""

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
"""How a simulated server answers a request."""


def _form(action: str, fields: dict[str, str], extra: str = "") -> str:
    inputs = "".join(f'<input type="hidden" name="{name}" value="{value}"/>' for name, value in fields.items())
    return f'<html><body><form method="post" action="{action}">{inputs}{extra}</form></body></html>'


class SimulatedAulaLogin:
    """Aula's login chain on a local test server, with a simulated MitID behind it.

    Use it as an async context manager; `client(session, user_id)` then gives a login client
    pointed at it.
    """

    def __init__(
        self,
        users: Iterable[str] | Mapping[str, User] | None = None,
        identities: list[str] | None = None,
        network: Network | None = None,
    ) -> None:
        """A chain whose MitID knows `users` - user IDs with the app only, or each user ID's `User` - and offers `identities`."""
        self.network = network or Network()
        self.mitid = SimulatedMitID(users if users is not None else {"parent"}, network=self.network)
        self.identities = identities or []
        """The identities NemLog-in offers to choose between; none, one is taken at once."""
        self.chosen_identity: str | None = None
        self.loginoption_query = ""
        """A query NemLog-in adds to the page it sends to choose an identity on, such as `?lang=da`."""
        self.role_selection = True
        """Whether the broker asks for the role, as it does for a guardian who is also a pupil."""
        self.confirmation_page = True
        """Whether the broker shows its confirmation page before going back to Aula."""
        self.refresh_tokens: dict[str, str] = {}
        """The refresh tokens issued, and the access token each was issued with."""
        self.renewals = 0
        """How many times an access token was renewed with a refresh token."""
        self.revoked: set[str] = set()
        self.answers: dict[str, Handler] = {}
        """Answers that replace a step's own, by its method and path, such as "GET /broker/back-to-aula",
        for the answers the real chain gives only now and then."""
        self._state = ""
        self._code_challenge = ""
        self._code = ""
        self._verification_token = secrets.token_hex(8)
        self._saml_mitid = secrets.token_hex(8)
        self._saml_aula = secrets.token_hex(8)
        self._server: TestServer | None = None
        self.app = web.Application(middlewares=[self.network.middleware, self._answer])
        self.app.add_routes(
            [
                web.get("/login/simplesaml/module.php/oidc/authorize.php", self._authorize),
                web.get("/broker/auth/realms/broker/protocol/saml", self._broker_start),
                web.post("/broker/select", self._broker_select),
                web.get("/nemlogin/login/mitid", self._nemlogin_page),
                web.post("/nemlogin/login/mitid/initialize", self._nemlogin_initialize),
                web.post("/nemlogin/login/mitid", self._nemlogin_complete),
                web.get("/nemlogin/loginoption", self._loginoption_page),
                web.post("/nemlogin/loginoption", self._loginoption_choose),
                web.post("/broker/auth/realms/broker/broker/nemlogin3/endpoint", self._broker_endpoint),
                web.get("/broker/first-broker-login", self._first_broker_login),
                web.post("/broker/auth/realms/broker/login-actions/post-broker-login", self._post_broker_login),
                web.post("/broker/confirm", self._confirm),
                web.get("/broker/back-to-aula", self._back_to_aula),
                web.post("/login/simplesaml/module.php/saml/sp/saml2-acs.php/uni-sp", self._aula_acs),
                web.get("/login/oidc/callback", self._oidc_callback),
                web.post("/login/simplesaml/module.php/oidc/token.php", self._token),
            ]
        )

    async def __aenter__(self) -> Self:
        await self.mitid.__aenter__()
        self._server = TestServer(self.app)
        await self._server.start_server(access_log=None)
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._server is not None:
            await self._server.close()
        await self.mitid.__aexit__(exc_type, exc, tb)

    @property
    def url(self) -> str:
        """The base URL the simulated login chain answers at."""
        assert self._server is not None, "use the simulated Aula login as an async context manager"
        return str(self._server.make_url("")).rstrip("/")

    def point(self, client: AulaLoginClient) -> AulaLoginClient:
        """Point a login client at the simulated chain instead of the real one."""
        client.auth_base_url = f"{self.url}/login"
        client.broker_url = f"{self.url}/broker"
        client.nemlogin_url = f"{self.url}/nemlogin"
        client.mitid_url = self.mitid.url
        return client

    @web.middleware
    async def _answer(self, request: web.Request, handler: Handler) -> web.StreamResponse:
        answer = self.answers.get(f"{request.method} {request.path}")
        return await (answer or handler)(request)

    @staticmethod
    def _need_cookie(request: web.Request, name: str, value: str | None = None) -> None:
        if name not in request.cookies or (value is not None and request.cookies[name] != value):
            raise web.HTTPForbidden(text=f"missing cookie {name}")

    async def _authorize(self, request: web.Request) -> web.Response:
        query = request.query
        if query.get("code_challenge_method") != "S256" or query.get("response_type") != "code":
            raise web.HTTPBadRequest(text="not a PKCE code request")
        if query.get("redirect_uri") != APP_REDIRECT_URI:
            raise web.HTTPBadRequest(text="unknown redirect_uri")
        self._state = query["state"]
        self._code_challenge = query["code_challenge"]
        # Set as it is: aiohttp would normalise the URL of a redirect it builds itself.
        response = web.Response(
            status=302,
            headers={"Location": f"{self.url}/broker/auth/realms/broker/protocol/saml?SAMLRequest=a%2Bb%2Fc%3D"},
        )
        response.set_cookie("SimpleSAMLSessionID", "aula-session")
        return response

    async def _broker_start(self, request: web.Request) -> web.Response:
        if request.rel_url.raw_query_string != "SAMLRequest=a%2Bb%2Fc%3D":
            raise web.HTTPBadRequest(text="the SAML request was re-encoded")
        response = web.Response(
            text=_form(f"{self.url}/broker/select", {"kc_idp_hint": ""}), content_type="text/html"
        )
        response.set_cookie("AUTH_SESSION_ID", "broker-session")
        return response

    async def _broker_select(self, request: web.Request) -> web.Response:
        self._need_cookie(request, "AUTH_SESSION_ID", "broker-session")
        form = await request.post()
        if form.get("selectedIdp") != "nemlogin3":
            return web.Response(text="unknown identity provider", status=400)
        raise web.HTTPFound(f"{self.url}/nemlogin/login/mitid")

    async def _nemlogin_page(self, request: web.Request) -> web.Response:
        response = web.Response(
            text=_form("/login/mitid", {"__RequestVerificationToken": self._verification_token}),
            content_type="text/html",
        )
        response.set_cookie("SessionUuid", "nemlogin-session")
        response.set_cookie("Challenge", "nemlogin-challenge")
        return response

    async def _nemlogin_initialize(self, request: web.Request) -> web.Response:
        self._need_cookie(request, "SessionUuid")
        form = await request.post()
        if form.get("__RequestVerificationToken") != self._verification_token:
            return web.Response(text="bad verification token", status=400)
        aux = base64.b64encode(json.dumps(self.mitid.new_login()).encode()).decode()
        # NemLog-in answers with the JSON object as a JSON string.
        return web.json_response(json.dumps({"Aux": aux}))

    def _saml_page(self) -> web.Response:
        return web.Response(
            text=_form(
                f"{self.url}/broker/auth/realms/broker/broker/nemlogin3/endpoint",
                {"RelayState": "relay-mitid", "SAMLResponse": self._saml_mitid},
            ),
            content_type="text/html",
        )

    async def _nemlogin_complete(self, request: web.Request) -> web.Response:
        self._need_cookie(request, "SessionUuid")
        form = await request.post()
        if (
            form.get("MitIDAuthCode") != self.mitid.authorization_code
            or form.get("__RequestVerificationToken") != self._verification_token
            or form.get("SessionStorageActiveSessionUuid") != "nemlogin-session"
            or form.get("SessionStorageActiveChallenge") != "nemlogin-challenge"
        ):
            return web.Response(text="MitID login not completed", status=400)
        if len(self.identities) > 1:
            raise web.HTTPSeeOther(f"{self.url}/nemlogin/loginoption{self.loginoption_query}")
        return self._saml_page()

    async def _loginoption_page(self, request: web.Request) -> web.Response:
        options = "".join(
            f'<a class="list-link" data-loginoptions=\'{{"id":{index}}}\'><div class="list-link-text">{name}</div></a>'
            for index, name in enumerate(self.identities)
        )
        return web.Response(
            text=_form("/loginoption", {"__RequestVerificationToken": self._verification_token}) + options,
            content_type="text/html",
        )

    async def _loginoption_choose(self, request: web.Request) -> web.Response:
        self._need_cookie(request, "SessionUuid")
        form = await request.post()
        chosen = json.loads(str(form.get("ChosenOptionJson", "{}")))
        self.chosen_identity = self.identities[int(chosen["id"])]
        return self._saml_page()

    async def _broker_endpoint(self, request: web.Request) -> web.Response:
        self._need_cookie(request, "AUTH_SESSION_ID", "broker-session")
        form = await request.post()
        if form.get("SAMLResponse") != self._saml_mitid or form.get("RelayState") != "relay-mitid":
            return web.Response(text="bad SAML response", status=400)
        raise web.HTTPFound(f"{self.url}/broker/first-broker-login?session_code=sc&execution=ex&client_id=aula&tab_id=t1")

    async def _first_broker_login(self, request: web.Request) -> web.Response:
        self._need_cookie(request, "AUTH_SESSION_ID", "broker-session")
        fields = {"username": "guardian"}
        if self.role_selection:
            fields["selected-aktoer"] = "ELEV"
        query = urlencode({"session_code": "sc", "execution": "ex", "client_id": "aula", "tab_id": "t1"})
        return web.Response(
            text=_form(f"{self.url}/broker/auth/realms/broker/login-actions/post-broker-login?{query}", fields),
            content_type="text/html",
        )

    async def _post_broker_login(self, request: web.Request) -> web.Response:
        self._need_cookie(request, "AUTH_SESSION_ID", "broker-session")
        form = await request.post()
        if request.query.get("session_code") != "sc" or request.query.get("execution") != "ex":
            return web.Response(text="lost the broker session", status=400)
        if self.role_selection and form.get("selected-aktoer") != "KONTAKT":
            return web.Response(text="a guardian logs in as KONTAKT", status=400)
        if self.confirmation_page:
            button = '<button id="confirmation-button" type="submit">Continue</button>'
            return web.Response(text=_form("/broker/confirm", {"confirmed": "yes"}, button), content_type="text/html")
        raise web.HTTPFound(f"{self.url}/broker/back-to-aula")

    async def _confirm(self, request: web.Request) -> web.Response:
        self._need_cookie(request, "AUTH_SESSION_ID", "broker-session")
        if (await request.post()).get("confirmed") != "yes":
            return web.Response(text="not confirmed", status=400)
        raise web.HTTPFound(f"{self.url}/broker/back-to-aula")

    async def _back_to_aula(self, request: web.Request) -> web.Response:
        self._need_cookie(request, "AUTH_SESSION_ID", "broker-session")
        return web.Response(
            text=_form(
                f"{self.url}/login/simplesaml/module.php/saml/sp/saml2-acs.php/uni-sp",
                {"SAMLResponse": self._saml_aula, "RelayState": "relay-aula"},
            ),
            content_type="text/html",
        )

    async def _aula_acs(self, request: web.Request) -> web.Response:
        self._need_cookie(request, "SimpleSAMLSessionID", "aula-session")
        if (await request.post()).get("SAMLResponse") != self._saml_aula:
            return web.Response(text="bad SAML response", status=400)
        raise web.HTTPFound(f"{self.url}/login/oidc/callback")

    async def _oidc_callback(self, request: web.Request) -> web.Response:
        self._need_cookie(request, "SimpleSAMLSessionID", "aula-session")
        self._code = secrets.token_hex(8)
        raise web.HTTPFound(f"{APP_REDIRECT_URI}?{urlencode({'code': self._code, 'state': self._state})}")

    def _issue(self) -> web.Response:
        access, refresh = f"access-{secrets.token_hex(4)}", f"refresh-{secrets.token_hex(4)}"
        self.refresh_tokens[refresh] = access
        return web.json_response({"access_token": access, "refresh_token": refresh, "expires_in": 3600, "token_type": "Bearer"})

    async def _token(self, request: web.Request) -> web.Response:
        form = await request.post()
        if form.get("grant_type") == "refresh_token":
            refresh = str(form.get("refresh_token"))
            if refresh not in self.refresh_tokens or refresh in self.revoked:
                return web.json_response({"error": "invalid_grant"}, status=400)
            self.revoked.add(refresh)
            self.renewals += 1
            return self._issue()
        verifier = str(form.get("code_verifier", ""))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        if form.get("code") != self._code or challenge != self._code_challenge:
            return web.json_response({"error": "invalid_grant"}, status=400)
        self._code = ""
        return self._issue()


def _day(value: object) -> datetime.date | None:
    """A date written "YYYY-MM-DD", as Aula takes one; None for anything else."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def _jwt(lifetime: float = 3600) -> str:
    def part(value: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'exp': int(time.time() + lifetime)})}.signature"


class SimulatedAulaApi:
    """Aula's API and its widgets' (Meebook, EasyIQ, MinUddannelse) on a local test server.

    It answers with the account and data a test gives it, in Aula's own formats, and checks what
    Aula checks: the access token on every request, the CSRF token on every POST, and the widget
    token on every widget request. Use it as an async context manager, and `point` an API client
    at it.
    """

    VERSION = 25

    _THREAD: dict[str, object] = {
        "extraRecipientsCount": 0,
        "isArchived": False,
        "isThreadOrSubscriptionDeleted": False,
        "marked": False,
        "muted": False,
        "read": False,
        "startedTime": "2026-12-28T08:00:00+00:00",
    }
    """What Aula sends of a thread besides what a test gives."""
    _THREAD_PAGE: dict[str, object] = {
        "hasSecureDocuments": False,
        "isArchived": False,
        "marked": False,
        "moreMessagesExist": False,
        "muted": False,
        "page": 0,
        "recipients": [],
        "sensitive": False,
        "subject": "",
        "threadStartedDateTime": "2026-12-28T08:00:00+00:00",
    }
    """What Aula sends of a page of a thread's messages besides the messages."""
    _MESSAGE: dict[str, object] = {"canReplyToMessage": True, "hasAttachments": False}
    """What Aula sends of a message besides what a test gives."""
    _EVENT: dict[str, object] = {"hasAttachments": False, "requiresNewAnswer": False, "responseRequired": False}
    """What Aula sends of a calendar event besides what a test gives."""
    _LISTED_ONLY = frozenset(
        {
            "belongsToProfiles", "belongsToResources", "createdDateTime", "creatorInstProfileId", "creatorName",
            "creatorProfileId", "directlyRelated", "hasAttachments", "requiresNewAnswer", "responseStatus",
            "vacationChildrenCountByDates",
        }
    )
    """What Aula sends of a calendar event in the list of events, and not of the event alone."""
    _DETAIL: dict[str, object] = {
        "description": {"html": "<p>Mere om det</p>"},
        "attachments": [],
        "coOrganizers": [],
        "invitees": [],
        "inviteeGroups": [],
        "isDeadlineExceeded": False,
        "isDeleted": False,
        "responseRequired": False,
    }
    """What Aula sends of a calendar event alone besides what is listed of it."""

    def __init__(
        self, access_token: str = "access", network: Network | None = None, login: SimulatedAulaLogin | None = None
    ) -> None:
        self.access_token = access_token
        self.version = self.VERSION
        """The version the API is at now; Aula answers 410 Gone at an older one."""
        self.network = network or Network()
        self.login = login
        """The login chain whose access tokens the API accepts too, as Aula's API accepts its own."""
        self.csrf_token = secrets.token_hex(8)
        self.stepped_up = False
        """Whether the login has stepped up to MitID's higher level."""
        self.widgets = ["0001", "0004", "0029"]
        self.widget_fields: dict[str, dict[str, object]] = {}
        """Aula's further fields of a widget, such as its "widgetSupplier" and "url", by its id."""
        self.guardian = {"profileId": 201, "displayName": "Pat Example", "userId": "pat"}
        self.institution = {"id": 21, "institutionCode": "S1", "institutionName": "School"}
        self.child = {
            "id": 11,
            "institutionCode": "S1",
            "institutionProfile": {"id": 11, "institutionCode": "S1", "institutionName": "School"},
            "name": "Alma Example",
            "profileId": 101,
            "shortName": "AE",
            "userId": "alma",
        }
        self.daily_overviews: list[dict[str, object]] = []
        self.threads: list[dict[str, object]] = []
        self.messages: dict[int, list[dict[str, object]]] = {}
        self.notifications: list[dict[str, object]] = []
        self.events: list[dict[str, object]] = []
        self.event_details: dict[int, dict[str, object]] = {}
        """What Aula sends of an event alone besides what it lists of it, by the event's id."""
        self.birthdays: list[dict[str, object]] = []
        self.weekly_plans: list[dict[str, object]] = []
        self.easyiq_events: list[dict[str, object]] = []
        self.newsletters: list[dict[str, object]] = []
        self.presence_modules: dict[str, str] = {"report_sick": "editable", "vacation": "editable"}
        """The permission of each part of the presence module on the guardian's dashboard, by its name, for the child."""
        self.presence_statuses: dict[int, int] = {}
        """The status each child was reported to have today, by its institution profile id, over its daily overview's."""
        self.vacations: list[dict[str, object]] = []
        """The vacations registered: Aula's fields of each, and "childIds", the children it is for."""
        self.vacation_requests: list[dict[str, object]] = []
        """The institution's vacation requests: Aula's listed fields of each, such as "responseId", and "childId"."""
        self.vacation_answers: dict[int, dict[str, object]] = {}
        """The answer to each vacation request, its "comment" and "days", by its "responseId"."""
        self._ids = itertools.count(9001)
        self.widget_tokens: set[str] = set()
        self.widget_token_lifetime = 3600.0
        """Seconds a widget token is valid for when handed out; Aula now and then hands out one expired already."""
        self.requests: list[str] = []
        """The Aula API methods and widget paths asked for, in order."""
        self.meebook_requests: list[tuple[dict[str, str], str]] = []
        """Each request to Meebook: its query, and the session it names in the sessionuuid header."""
        self.posts: list[dict[str, object]] = [
            {
                "id": 501,
                "title": "Juleklip fredag",
                "content": {"html": "<p>Hele skolen klipper julepynt fredag.</p>"},
                "timestamp": "2026-11-23T08:00:00+00:00",
                "publishAt": "2026-11-23T08:00:00+00:00",
                "editedAt": None,
                "expireAt": "2027-11-23T08:00:00+00:00",
                "isImportant": False,
                "importantFrom": None,
                "importantTo": None,
                "commentCount": 0,
                "attachments": [],
                "ownerProfile": {"fullName": "Kontoret", "institution": {"institutionName": "School"}},
                "sharedWithGroups": [{"name": "Hele skolen"}],
                "relatedProfiles": [{"id": 11, "role": "child"}],
            }
        ]
        """The news feed's posts, the newest first, in Aula's fields."""
        self.posts_last_seen = "2026-11-20T08:00:00+00:00"
        """When the guardian last saw the posts, as Aula keeps it."""
        self.reading_posts_sees_them = False
        """Whether reading the posts moves when they were last seen to that moment."""
        self.closed_days: list[dict[str, object]] = [{"name": "Juleferie", "startDate": "2026-12-21", "endDate": "2027-01-01"}]
        """The days the child's institution is closed, in Aula's fields."""
        self.opening_hours: list[dict[str, object]] = [
            {"date": "2026-12-18", "type": "general_opening_hours", "openTime": "06:30", "closeTime": "17:00"},
            {"date": "2026-12-21", "type": "closed_day", "openTime": None, "closeTime": None},
        ]
        """The child's institution's hours, day by day, in Aula's fields."""
        self.catalog: dict[str, object] = {
            "gallery.getAlbums": [{"id": 701, "title": "Udflugt"}],
            "gallery.getMedia": {"results": [{"id": 801}]},
            "gallery.getMediaById": {"id": 801},
            "groups.getGroupById": {},
            "presence.getPresenceTemplates": {},
            "Notifications.getNotificationSettingsForActiveProfile": {},
            "commonFiles.getCommonFiles": {},
        }
        """What Aula answers each other method of its catalog that only reads with, by its name; an
        empty list where none is given."""
        self.answers: dict[str, Handler] = {}
        """Answers that replace the API's own: by the Aula API method, such as "presence.getDailyOverview",
        or by the method and path of a widget's request, such as "GET /aulaapi/relatedweekplan/all"."""
        self._server: TestServer | None = None
        self.app = web.Application(middlewares=[self.network.middleware, self._answer])
        self.app.add_routes(
            [
                web.get("/api/v{version:[0-9]+}", self._api),
                web.post("/api/v{version:[0-9]+}", self._api),
                web.get("/aulaapi/relatedweekplan/all", self._meebook),
                web.post("/easyiq/weekplaninfo", self._easyiq),
                web.get("/minuddannelse/ugebrev", self._minuddannelse),
            ]
        )

    async def __aenter__(self) -> Self:
        self._server = TestServer(self.app)
        await self._server.start_server(access_log=None)
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._server is not None:
            await self._server.close()

    @property
    def url(self) -> str:
        """The base URL the simulated API answers at."""
        assert self._server is not None, "use the simulated Aula API as an async context manager"
        return str(self._server.make_url("")).rstrip("/")

    def point(self, client: AulaProxyClient) -> AulaProxyClient:
        """Point an API client at the simulated API and widgets instead of the real ones."""
        client.use_api(f"{self.url}/api/v")
        client.api_version = self.VERSION
        client.meebook_api = f"{self.url}/aulaapi"
        client.easyiq_api = f"{self.url}/easyiq"
        client.min_uddannelse_api = f"{self.url}/minuddannelse"
        return client

    @web.middleware
    async def _answer(self, request: web.Request, handler: Handler) -> web.StreamResponse:
        key = request.query.get("method", "") if request.path.startswith("/api/") else f"{request.method} {request.path}"
        answer = self.answers.get(key)
        return await (answer or handler)(request)

    @staticmethod
    def _ok(data: object) -> web.Response:
        return web.json_response({"status": {"code": 0, "message": "OK"}, "data": data, "version": SimulatedAulaApi.VERSION})

    def _widget_token_valid(self, request: web.Request) -> bool:
        authorization = request.headers.get("Authorization", "")
        return authorization.startswith("Bearer ") and authorization.removeprefix("Bearer ") in self.widget_tokens

    async def _api(self, request: web.Request) -> web.Response:
        version = int(request.match_info["version"])
        if version != self.version:
            status = 410 if version < self.version else 404
            return web.json_response({"status": {"code": status, "message": "Not this version"}}, status=status)
        token = request.query.get("access_token")
        issued = self.login.refresh_tokens.values() if self.login is not None else ()
        if token != self.access_token and token not in issued:
            return web.json_response({"status": {"code": 448, "message": "Unauthorized"}}, status=401)
        if request.method == "POST" and request.headers.get("csrfp-token") != self.csrf_token:
            return web.json_response({"status": {"code": 403, "message": "CSRF"}}, status=403)
        method = request.query.get("method", "")
        self.requests.append(method)
        match method:
            case "profiles.getProfilesByLogin":
                profile = {
                    **{name: value for name, value in self.guardian.items() if name != "userId"},
                    "children": [self.child],
                    "institutionProfiles": [self.institution],
                }
                response = self._ok({"profiles": [profile]})
                response.set_cookie("Csrfp-Token", self.csrf_token)
                return response
            case "profiles.getProfileContext":
                widgets = [
                    {"id": index, "widget": {"widgetId": widget, "name": widget, "id": index, **self.widget_fields.get(widget, {})}}
                    for index, widget in enumerate(self.widgets)
                ]
                return self._ok(
                    {
                        "userId": self.guardian["userId"],
                        "isSteppedUp": self.stepped_up,
                        "institutionProfile": {"role": "guardian"},
                        "institutions": [
                            {
                                "institutionCode": self.child["institutionCode"],
                                "children": [{"id": self.child["id"], "userId": self.child["userId"]}],
                            }
                        ],
                        "pageConfiguration": {"widgetConfigurations": widgets},
                    }
                )
            case "profiles.getProfileMasterData":
                return self._ok(
                    {
                        "institutionProfiles": [
                            {"relations": [{"id": self.child["id"], "mainGroup": {"id": 1, "name": "3A", "shortName": "3A"}}]}
                        ]
                    }
                )
            case "presence.getDailyOverview":
                return self._ok([self._with_status(overview) for overview in self.daily_overviews])
            case "messaging.getThreads":
                threads = [{**self._THREAD, "institutionCode": self.child["institutionCode"], **thread} for thread in self.threads]
                return self._ok({"moreMessagesExist": False, "page": 0, "threads": threads})
            case "messaging.getMessagesForThread":
                thread_id = int(request.query["threadId"])
                messages = [{**self._MESSAGE, **message} for message in self.messages.get(thread_id, [])]
                creator = {"answerDirectlyName": "Pat Example", "fullName": "Pat Example", "metadata": "School"}
                return self._ok(
                    {
                        **self._THREAD_PAGE,
                        "id": thread_id,
                        "institutionCode": self.child["institutionCode"],
                        "lastReadMessageId": str(messages[-1]["id"]) if messages else "",
                        "messages": messages,
                        "threadCreator": creator,
                        "totalMessageCount": len(messages),
                    }
                )
            case "notifications.getNotificationsForActiveProfile":
                return self._ok(self.notifications)
            case "calendar.getEventsByProfileIdsAndResourceIds":
                return self._ok([{**self._EVENT, **event} for event in self.events])
            case "calendar.getEventById":
                event_id = request.query.get("eventId", "")
                found = [event for event in self.events if str(event.get("id")) == event_id]
                if not found:
                    return web.json_response({"status": {"code": 40, "message": ""}, "data": None}, status=400)
                listed = {name: value for name, value in found[0].items() if name not in self._LISTED_ONLY}
                return self._ok({**self._DETAIL, **listed, **self.event_details.get(int(event_id), {})})
            case "calendar.getBirthdayEventsForInstitutions":
                return self._ok(self.birthdays)
            case "aulaToken.getAulaToken":
                token = _jwt(self.widget_token_lifetime)
                self.widget_tokens.add(token)
                return self._ok(token)
            case (
                "presence.getPresenceConfigurationByChildIds"
                | "presence.getVacationAnnouncementsByChildren"
                | "presence.getVacationRegistrationsByChildren"
                | "presence.getVacationRegistrationResponse"
            ):
                return self._presence(method, request)
            case (
                "presence.updateStatusByInstitutionProfileIds"
                | "calendar.addVacation"
                | "calendar.deleteEvent"
                | "calendar.respondToVacationRegistrationRequest"
                | "messaging.reply"
            ):
                try:
                    body: object = await request.json()
                except ValueError:
                    return self._refused()
                return self._write(method, cast(dict[str, Any], body)) if isinstance(body, dict) else self._refused()
            case "posts.getAllPosts":
                answer = self._ok({"posts": self.posts, "hasMorePosts": False, "profileLastSeenPostDate": self.posts_last_seen})
                if self.reading_posts_sees_them:
                    self.posts_last_seen = datetime.datetime.now(datetime.timezone.utc).isoformat()
                return answer
            case "posts.getById":
                post_id = request.query.get("id", "")
                post = next((post for post in self.posts if str(post.get("id")) == post_id), None)
                return self._ok(post) if post is not None else self._refused()
            case "presence.getClosedDays":
                overview = {"closedDays": self.closed_days}
                return self._ok({"institutionClosedDays": [{"institutionCode": self.child["institutionCode"], "closedDaysOverview": overview}]})
            case "presence.getOpeningHoursByInstitutionCodes":
                days = [{"institutionCode": self.child["institutionCode"], "openingHoursDto": self.opening_hours}]
                return self._ok({"openingHoursOverviewDto": days})
            case _ if (found := known(method)) is not None and found.readable and found.verb == "GET":
                return self._ok(self.catalog.get(method, []))
            case _:
                return web.json_response({"status": {"code": 404, "message": f"Unknown method {method}"}}, status=404)

    @staticmethod
    def _refused() -> web.Response:
        """Aula's answer to parameters or a body it does not take."""
        return web.json_response({"status": {"code": 40, "message": ""}, "data": None}, status=400)

    def _with_status(self, overview: dict[str, object]) -> dict[str, object]:
        profile = cast(dict[str, object], overview.get("institutionProfile") or {})
        status = self.presence_statuses.get(cast(int, profile.get("id")))
        return overview if status is None else {**overview, "status": status}

    def _child_ids(self, request: web.Request) -> list[int] | None:
        """The children asked for, None where one is none of the account's."""
        ids = request.query.getall("childIds[]", [])
        if not ids or any(child_id != str(self.child["id"]) for child_id in ids):
            return None
        return [int(child_id) for child_id in ids]

    def _request(self, response_id: object) -> dict[str, object] | None:
        return next((found for found in self.vacation_requests if found.get("responseId") == response_id), None)

    def _presence(self, method: str, request: web.Request) -> web.Response:
        if method == "presence.getVacationRegistrationResponse":
            found = self._request(int(request.query.get("vacationRegistrationResponseId") or 0))
            if found is None:
                return self._refused()
            answer = self.vacation_answers.get(cast(int, found["responseId"]), {})
            period = ("startDate", "endDate", "responseDeadline", "isPresenceTimesRequired")
            return self._ok(
                {
                    "vacationRegistrationResponse": {
                        "vacationRegistrationResponseId": found["responseId"],
                        "childId": found["childId"],
                        "comment": answer.get("comment", ""),
                        "days": answer.get("days", []),
                    },
                    "vacationRegistration": {
                        **{name: found.get(name) for name in period},
                        "isMissingAnswer": not answer,
                    },
                }
            )
        children = self._child_ids(request)
        if children is None:
            return self._refused()
        child = {name: self.child.get(name) for name in ("id", "name", "shortName")}
        if method == "presence.getPresenceConfigurationByChildIds":
            modules = [{"moduleType": name, "permission": permission} for name, permission in self.presence_modules.items()]
            settings = [{"presenceDashboardContext": "guardian_dashboard", "presenceModules": modules}]
            return self._ok([{"uniStudentId": child_id, "presenceConfiguration": {"dashboardModuleSettings": settings}} for child_id in children])
        if method == "presence.getVacationAnnouncementsByChildren":
            vacations = [
                {name: value for name, value in vacation.items() if name != "childIds"}
                for vacation in self.vacations
                if self.child["id"] in cast(list[int], vacation["childIds"])
            ]
            return self._ok([{"child": child, "vacationAnnouncements": vacations}])
        requests = [
            {
                **{name: value for name, value in found.items() if name != "childId"},
                "isMissingAnswer": found["responseId"] not in self.vacation_answers,
            }
            for found in self.vacation_requests
            if found.get("childId") == self.child["id"]
        ]
        return self._ok([{"child": child, "vacationRegistrations": requests}])

    def _write(self, method: str, body: dict[str, Any]) -> web.Response:
        """Do what a write asks, where its body is the one Aula's portal sends; refuse it otherwise."""
        match method:
            case "presence.updateStatusByInstitutionProfileIds":
                status: object = body.get("status")
                ok = set(body) == {"institutionProfileIds", "status"} and self._children(body["institutionProfileIds"])
                if not ok or type(status) is not int or status not in (0, 1):
                    return self._refused()
                for child_id in cast(list[int], body["institutionProfileIds"]):
                    self.presence_statuses[child_id] = status
                return self._ok(None)
            case "calendar.addVacation":
                intervals = body.get("intervals")
                if (
                    set(body) != {"childIds", "intervals", "comment"}
                    or not self._children(body["childIds"])
                    or not isinstance(body["comment"], str)
                    or len(body["comment"]) > 250
                    or not isinstance(intervals, list)
                    or len(cast(list[object], intervals)) != 1
                ):
                    return self._refused()
                [interval] = cast(list[object], intervals)
                if not isinstance(interval, dict) or set(cast(dict[str, object], interval)) != {"startDate", "endDate"}:
                    return self._refused()
                start, end = (_day(cast(dict[str, object], interval)[name]) for name in ("startDate", "endDate"))
                if start is None or end is None or end < start:
                    return self._refused()
                self.vacations.append(
                    {
                        "vacationId": next(self._ids),
                        "startDate": start.isoformat(),
                        "endDate": end.isoformat(),
                        "description": body["comment"],
                        "isEditable": True,
                        "childIds": list(cast(list[int], body["childIds"])),
                    }
                )
                return self._ok(None)
            case "calendar.deleteEvent":
                found = [vacation for vacation in self.vacations if set(body) == {"id"} and vacation["vacationId"] == body["id"]]
                if not found:
                    return self._refused()
                self.vacations.remove(found[0])
                return self._ok(None)
            case "calendar.respondToVacationRegistrationRequest":
                found = self._request(body.get("vacationRegistrationResponseId"))
                if (
                    found is None
                    or set(body) != {"vacationRegistrationResponseId", "childId", "days", "comment"}
                    or body["childId"] != found["childId"]
                    or not isinstance(body["comment"], str)
                    or not isinstance(body["days"], list)
                    or not body["days"]
                    or not all(self._answered_day(found, day) for day in cast(list[object], body["days"]))
                ):
                    return self._refused()
                self.vacation_answers[cast(int, found["responseId"])] = {"comment": body["comment"], "days": body["days"]}
                return self._ok(None)
            case _:
                return self._reply(body)

    def _children(self, ids: object) -> bool:
        """Whether `ids` is a list of the account's children's institution profile ids."""
        if not isinstance(ids, list):
            return False
        found = cast(list[object], ids)
        return bool(found) and all(child_id == self.child["id"] for child_id in found)

    @staticmethod
    def _answered_day(request: dict[str, object], day: object) -> bool:
        """Whether `day` is a day of the request answered as Aula's portal answers it."""
        if not isinstance(day, dict) or set(cast(dict[str, object], day)) != {"date", "isComing", "entryTime", "exitTime"}:
            return False
        answer = cast(dict[str, object], day)
        on = _day(answer["date"])
        start, end = _day(request.get("startDate")), _day(request.get("endDate"))
        if on is None or start is None or end is None or not start <= on <= end or on.weekday() >= 5:
            return False
        if not isinstance(answer["isComing"], bool):
            return False
        times = (answer["entryTime"], answer["exitTime"])
        if answer["isComing"] and request.get("isPresenceTimesRequired"):
            clock = re.compile(r"[0-2][0-9]:[0-5][0-9]")
            return all(isinstance(at, str) and clock.fullmatch(at) for at in times) and str(times[0]) < str(times[1])
        return times == ("", "")

    def _reply(self, body: dict[str, Any]) -> web.Response:
        message = body.get("message")
        thread = next((found for found in self.threads if found.get("id") == body.get("threadId")), None)
        if (
            thread is None
            or set(body) != {"threadId", "message", "commonInboxId", "otpInboxId"}
            or body["commonInboxId"] is not None
            or body["otpInboxId"] is not None
            or not isinstance(message, dict)
            or set(cast(dict[str, object], message)) != {"text", "attachmentIds"}
            or cast(dict[str, object], message)["attachmentIds"] != []
        ):
            return self._refused()
        text = cast(dict[str, object], message)["text"]
        if not isinstance(text, str) or len(text) > 10000 or not 0 < len(re.sub(r"<[^>]*>", "", text).strip()) <= 6600:
            return self._refused()
        sent = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
        sender = {"answerDirectlyName": self.guardian["displayName"], "fullName": self.guardian["displayName"], "metadata": ""}
        reply: dict[str, object] = {"id": f"r{next(self._ids)}", "messageType": "Message", "sendDateTime": sent, "sender": sender, "text": {"html": text}}
        self.messages.setdefault(cast(int, thread["id"]), []).append(reply)
        thread["latestMessage"] = {"id": reply["id"], "sendDateTime": sent, "text": {"html": text}}
        return self._ok([reply])

    async def _meebook(self, request: web.Request) -> web.Response:
        self.requests.append("meebook")
        self.meebook_requests.append((dict(request.query), request.headers.get("sessionuuid", "")))
        if not self._widget_token_valid(request):
            return web.json_response({"message": "JWT-Token expired, please renew."}, status=401)
        return web.json_response(self.weekly_plans)

    async def _easyiq(self, request: web.Request) -> web.Response:
        self.requests.append("easyiq")
        if not self._widget_token_valid(request) or request.headers.get("csrfp-token") != self.csrf_token:
            return web.json_response({"message": "unauthorized"}, status=401)
        return web.json_response({"Events": self.easyiq_events})

    async def _minuddannelse(self, request: web.Request) -> web.Response:
        self.requests.append("minuddannelse")
        if not self._widget_token_valid(request):
            return web.json_response({"message": "unauthorized"}, status=401)
        return web.json_response({"personer": self.newsletters})


class _LocalResolver(AbstractResolver):
    """Resolves the host names given to this machine, and no other name."""

    def __init__(self, hosts: Iterable[str]) -> None:
        self.hosts = set(hosts)

    async def resolve(self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET) -> list[ResolveResult]:
        if host not in self.hosts:
            raise OSError(f"{host} is not simulated")
        return [{"hostname": host, "host": "127.0.0.1", "port": port, "family": socket.AF_INET, "proto": 0, "flags": 0}]

    async def close(self) -> None:
        return None


class SimulatedTabulex:
    """IST's login from Aula into Tabulex's parent portal, on a local test server under made-up host names.

    It follows what a real chain was measured to do up to Aula's identity provider's login page,
    and SimpleSAMLphp and WS-Federation beyond it. The widget's address, on IST's service
    provider, takes the form Aula's portal posts, checks its Aula token, sets the shared session
    cookie and redirects to Aula's identity provider, which redirects to its login page. That
    page sets the login's cookie and answers with SimpleSAMLphp's form to the service provider,
    which its script `post.js` clicks. The service provider takes the assertion and sends the
    browser on to the portal, which redirects to its WS-Federation sign-in; signed in, it answers
    with a form an inline script submits to the portal, which sets its own cookie and redirects
    to its page, loading scripts of its own site and of another. Without the login, the sign-in
    redirects to the choice of identity provider, a page a browser stays on. Use it as an async
    context manager, reached through `session()`.
    """

    SP = "saml.borger.tabulex.test"
    IDP = "borger-aula-login.tabulex.test"
    PORTAL = "foraeldre.tabulex.test"
    ELSEWHERE = "login.elsewhere.test"
    DOMAINS = ("tabulex.test",)
    """The domains a probe of the simulated chain follows."""
    API = "api.tabulex.test"
    """The host of the portal's API, which hands out a bearer token and takes it."""
    CDN = "static.cdn.test"
    """A host of scripts the portal loads, on no site of Tabulex's."""
    OTHER = "app.hjerne.test"
    """The host of another widget's service, which answers its form with a page of its own."""
    SCRIPT = (
        'angular.module("fravaer").service("api", function ($http) {'
        ' $http.get("/api/children"); $http.get("api/children/{childId}/absence"); $http.post("/api/fravaer/meldSyg");'
        ' $http.get("/Account/LogOff"); $http.get("/api/settings?from=2026-11-01"); var kind = "application/json";'
        ' var view = "views/fravaer.html"; var chunk = "scripts/chunk.js"; var logo = "/img/logo.png";'
        ' var cdn = "https://cdn.elsewhere.test/x/y"; var unknown = "api/{unknown}/x";'
        " $http.get('/api/PersonsAdgangTilBoern'); $http.get('/api/Fravaer/Idag/' + barn.Cpr); });"
    )
    """The text of the portal's own script, naming the addresses its code reads and changes."""
    CHUNK = 'define("fravaer", function () { return "/api/fravaer/syg"; });'
    """The text of a script the portal loads on demand."""
    AULA_PHP = "/simplesaml/module.php/tabulexaulalogin/aula.php"
    SSO = "/simplesaml/saml2/idp/SSOService.php"
    LOGIN = "/simplesaml/module.php/tabulexaulalogin/login.php"
    ACS = "/simplesaml/module.php/saml/sp/saml2-acs.php/aula"
    PRP = "/simplesaml/module.php/adfs/idp/prp.php"
    DISCO = "/simplesaml/module.php/saml/disco.php"

    def __init__(self, aula: SimulatedAulaApi) -> None:
        """A chain that takes the widget tokens `aula` hands out."""
        self.aula = aula
        self.leave_to_elsewhere = False
        """Whether Aula's identity provider sends the browser to a host outside Tabulex's."""
        self.needs_javascript = False
        """Whether the login page answers with a page that needs JavaScript, in place of its form."""
        self.loops = False
        """Whether Aula's identity provider redirects to itself for ever."""
        self.onward = "redirect"
        """How the service provider sends the browser on to the portal: "redirect", "refresh" or "script"."""
        self.moved_acs = False
        """Whether the service provider's assertion consumer answers a temporary redirect to where it moved."""
        self.assertion = secrets.token_hex(16)
        self.state = secrets.token_hex(12)
        self.sp_session = secrets.token_hex(8)
        self.login_token = secrets.token_hex(8)
        self.signed_in = secrets.token_hex(8)
        self.api_token = secrets.token_hex(16)
        self.xsrf = f"{secrets.token_hex(8)}/{secrets.token_hex(8)}"
        """The portal's XSRF token, which its cookie holds encoded and its API wants decoded in a header."""
        self.children: list[dict[str, object]] = [
            {"Cpr": "1234567890", "Fornavn": "Alma Marie", "Efternavn": "Example", "SkoleKode": "S1",
             "SkoleNavn": "Made-up School", "Klasse": "3A", "SkoleFravaerAdgang": True, "Pige": True},
        ]
        """The children the portal's API lists, each by its made-up CPR number."""
        self.sick_today: set[str] = set()
        """The CPR numbers of the children reported sick today."""
        self.sick_reports: list[str] = []
        """The CPR number of each sick report the portal took, in order."""
        self.refuse_reports = False
        """Whether the portal answers a sick report with a server error."""
        self.xsrf_cookie = True
        """Whether the portal's page sets the cookie with its XSRF token."""
        self.garbled = False
        """Whether the portal answers its list of children with what is no JSON."""
        self.cdn_script = ""
        """The text of the script the portal loads from another host, naming its API's addresses; set as it starts."""
        self.portal_session = base64.b64encode(secrets.token_bytes(39) + b"\xfb\xff").decode()
        """The portal's session, in base64 as a real portal's, with a "/" and padding."""
        self.forms: list[dict[str, str]] = []
        """Each form posted to the widget's address."""
        self.requests: list[str] = []
        """The method, host and path of each request, in order."""
        self._server: TestServer | None = None
        self.app = web.Application()
        self.app.add_routes([web.route("*", "/{path:.*}", self._handle)])

    async def __aenter__(self) -> Self:
        self._server = TestServer(self.app)
        await self._server.start_server(access_log=None)
        self.cdn_script = self._cdn_script()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._server is not None:
            await self._server.close()

    def _base(self, host: str) -> str:
        assert self._server is not None, "use the simulated Tabulex as an async context manager"
        return f"http://{host}:{self._server.make_url('').port}"

    @property
    def widget_url(self) -> str:
        """The address of Aula's Tabulex widget."""
        return f"{self._base(self.SP)}{self.AULA_PHP}?appid=made-up-app"

    @property
    def widget(self) -> dict[str, object]:
        """Aula's further fields of its Tabulex widget."""
        return {"widgetSupplier": "IST", "type": "sso", "isSecure": True, "url": self.widget_url}

    async def _absence(self, request: web.Request) -> web.StreamResponse:
        if request.headers.get("X-XSRF-TOKEN") != self.xsrf:
            error = {"Message": "An error has occurred.", "ExceptionMessage": "The token header was not found.", "ExceptionType": "System.InvalidOperationException"}
            return web.json_response(error, status=500)
        cprs = {str(child["Cpr"]) for child in self.children}
        name = request.path.rstrip("/").rsplit("/", 1)[-1]
        if request.method == "GET" and request.path == "/api/PersonsAdgangTilBoern":
            return web.Response(text="<html>", content_type="text/html") if self.garbled else web.json_response(self.children)
        if request.method == "GET" and request.path.startswith(("/api/Fravaer/Idag/", "/api/Fravaer/Imorgen/")) and name in cprs:
            sick = name in self.sick_today and "/Idag/" in request.path
            return web.json_response(
                {"Dag": "2026-11-24T00:00:00" if sick else None, "Aarsag": "Sygdom" if sick else None, "HarHalvdagsFravaerSetting": False,
                 "Trin": 3, "FoersteLektionAarsag": None, "SidsteLektionAarsag": None, "Heldag": sick}
            )
        if request.method == "GET" and request.path.startswith("/api/Fravaer/skoledage/") and name in cprs:
            return web.json_response([{"Dato": "2026-11-24T00:00:00", "SkoleDag": True}, {"Dato": "2026-11-29T00:00:00", "SkoleDag": False}])
        if request.method == "PUT" and request.path == "/api/Fravaer/MeldSygIdag/":
            sent: object = await request.json()
            cpr = cast(dict[str, object], sent).get("Cpr") if isinstance(sent, dict) else None
            if self.refuse_reports or not isinstance(cpr, str) or cpr not in cprs:
                return web.json_response({"Message": "An error has occurred."}, status=500)
            self.sick_reports.append(cpr)
            self.sick_today.add(cpr)
            return web.Response(status=200)
        return web.json_response({"Message": "No HTTP resource was found that matches the request URI."}, status=404)

    def point(self, client: AulaClient) -> AulaClient:
        """Point a client's Tabulex at this simulated portal, reached on its sessions."""
        client.use_tabulex(self.portal, self.session, ("elsewhere.test",))
        return client

    def _cdn_script(self) -> str:
        api = self._base(self.API)
        return f'fetch("{api}/v1/token").then(function () {{ return fetch("{api}/v1/children"); }});'

    def _api(self, request: web.Request) -> web.StreamResponse:
        if request.path == "/v1/token":
            return web.json_response({"access_token": self.api_token, "expires_in": 3600})
        if request.path == "/v1/children" and request.headers.get("Authorization") == f"Bearer {self.api_token}":
            return web.json_response({"children": [{"childId": 7713, "firstName": "Alma"}]})
        return web.Response(status=401)

    def _other(self, request: web.Request) -> web.StreamResponse:
        if request.path == "/rest/data/kids":
            return web.json_response([{"kidId": 55}])
        if request.path == "/rest/data/kid" and request.query.get("kidId") == "55":
            return web.json_response({"kidId": 55, "name": "Bo"})
        if request.method == "POST" and request.path == "/aula/login":
            rest = f"{self._base(self.OTHER)}/rest/"
            code = f'var rest = "{rest}"; get("data/kids"); get("data/kid?kidId");'
            return web.Response(text=f'<base href="/app/"><title>Hjerne</title><h1>Velkommen</h1><script>{code}</script>', content_type="text/html")
        return web.Response(status=404)

    @property
    def other_widget(self) -> dict[str, object]:
        """Aula's further fields of another widget that logs in to a service of its own."""
        return {"widgetSupplier": "Hjernen&Hjertet", "type": "sso", "url": f"{self._base(self.OTHER)}/aula/login"}

    @property
    def portal(self) -> str:
        """The address of the parent portal."""
        return f"{self._base(self.PORTAL)}/"

    def session(self) -> aiohttp.ClientSession:
        """A session that reaches the simulated hosts on this machine, and no other host."""
        return probe_session(self.connector())

    def connector(self) -> aiohttp.TCPConnector:
        """A connector that reaches the simulated hosts on this machine, and no other host."""
        hosts = {self.SP, self.IDP, self.PORTAL, self.ELSEWHERE, self.OTHER, self.API, self.CDN}
        return aiohttp.TCPConnector(resolver=_LocalResolver(hosts))

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        host = request.host.split(":")[0]
        self.requests.append(f"{request.method} {host}{request.path}")
        if host == self.SP:
            return await self._sp(request)
        if host == self.IDP:
            return self._idp(request)
        if host == self.PORTAL:
            return await self._portal(request)
        if host == self.CDN:
            return web.Response(text=self.cdn_script, content_type="application/javascript")
        if host == self.API:
            return self._api(request)
        if host == self.OTHER:
            return self._other(request)
        return web.Response(text="<p>Somewhere else</p>", content_type="text/html")

    @staticmethod
    def _post_page(action: str, fields: dict[str, str], simplesamlphp: bool) -> web.Response:
        inputs = "".join(f'<input type="hidden" name="{name}" value="{value}"/>' for name, value in fields.items())
        if simplesamlphp:
            text = (
                '<html><head><title>POST data</title><script src="/simplesaml/resources/post.js"></script></head><body>'
                "<noscript><p>Since your browser does not support JavaScript, press the button.</p></noscript>"
                f'<form method="post" action="{action}"><input type="submit" id="postLoginSubmitButton"/>{inputs}</form></body></html>'
            )
        else:
            text = (
                f'<html><head><title>Working...</title></head><body><form method="POST" action="{action}">{inputs}'
                '<noscript><input type="submit" value="Submit"/></noscript></form>'
                "<script>window.setTimeout('document.forms[0].submit()', 0);</script></body></html>"
            )
        return web.Response(text=text, content_type="text/html")

    async def _sp(self, request: web.Request) -> web.StreamResponse:
        if request.method == "POST" and request.path == self.AULA_PHP:
            form = {name: str(value) for name, value in (await request.post()).items()}
            names = {"sessionUUID", "isMobileApp", "aulaToken", "assuranceLevel", "userProfile", "childFilter", "institutionFilter", "group", "currentWeekNumber"}
            if (
                request.query.get("appid") != "made-up-app"
                or set(form) != names
                or form["aulaToken"] not in self.aula.widget_tokens
                or form["isMobileApp"] != "false"
                or form["assuranceLevel"] not in ("2", "3")
            ):
                return web.Response(text="<p>Der skete en fejl</p>", content_type="text/html", status=400)
            self.forms.append(form)
            response = web.Response(status=302, headers={"Location": f"{self._base(self.IDP)}{self.SSO}?spentityid={self.SP}&RelayState={self.portal}"})
            response.set_cookie("SimpleSAMLCitizenSessionID", self.sp_session, domain="tabulex.test", path="/")
            return response
        if request.method == "POST" and request.path == self.ACS and self.moved_acs:
            return web.Response(status=307, headers={"Location": f"{self.ACS}2"})
        if request.method == "POST" and request.path in (self.ACS, f"{self.ACS}2"):
            form = await request.post()
            if form.get("SAMLResponse") != self.assertion or request.cookies.get("SimpleSAMLCitizenSessionID") != self.sp_session:
                return web.Response(text="<p>Der skete en fejl</p>", content_type="text/html", status=403)
            relay = str(form.get("RelayState"))
            if self.onward == "refresh":
                response: web.Response = web.Response(text=f'<meta http-equiv="refresh" content="0; url={relay}">', content_type="text/html")
            elif self.onward == "script":
                response = web.Response(text=f'<title>Vent</title><script>location.replace("{relay}");</script>', content_type="text/html")
            else:
                response = web.Response(status=303, headers={"Location": relay})
            response.set_cookie("SimpleSAMLCitizenAuthToken", self.signed_in, domain="tabulex.test", path="/")
            return response
        if request.path == self.PRP:
            if request.cookies.get("SimpleSAMLCitizenAuthToken") != self.signed_in:
                return web.Response(status=302, headers={"Location": f"{self.DISCO}?entityID={self.SP}&return=/discoresp.php"})
            return self._post_page(self.portal, {"wa": "wsignin1.0", "wresult": self.assertion, "wctx": "rm=0"}, simplesamlphp=False)
        if request.path == self.DISCO:
            return web.Response(
                text='<title>Vælg institution (identitetsudbyder)</title><form id="identform" method="get" action="/simplesaml/module.php/saml/disco.php">'
                '<input type="hidden" name="return" value="/discoresp.php"/><input type="hidden" id="idpentityid" name="idpentityid" value=""/></form>'
                '<script src="/jquery.js"></script><button onclick="$(\'#identform\').submit();">Vælg log-in</button>'
                "<script>function choose() { $('#identform').submit(); }</script>",
                content_type="text/html",
            )
        return web.Response(text="<p>Der skete en fejl</p>", content_type="text/html", status=403)

    def _idp(self, request: web.Request) -> web.StreamResponse:
        signed = request.cookies.get("SimpleSAMLCitizenSessionID") == self.sp_session
        if request.path == "/simplesaml/resources/post.js":
            return web.Response(text="window.onload = function () { document.getElementById('postLoginSubmitButton').click(); };", content_type="application/javascript")
        if request.path == self.SSO and signed:
            if self.loops:
                return web.Response(status=302, headers={"Location": f"{self.SSO}?again=1"})
            if self.leave_to_elsewhere:
                return web.Response(status=302, headers={"Location": f"{self._base(self.ELSEWHERE)}/login?SAMLRequest={self.assertion}"})
            return web.Response(status=302, headers={"Location": f"{self.LOGIN}?AuthState={self.state}"})
        if request.path == self.LOGIN and signed and request.query.get("AuthState") == self.state:
            if self.needs_javascript:
                response = web.Response(text='<div id="login"></div><script src="/login.js"></script>', content_type="text/html")
            else:
                fields = {"SAMLResponse": self.assertion, "RelayState": self.portal}
                response = self._post_page(f"{self._base(self.SP)}{self.ACS}", fields, simplesamlphp=True)
            response.set_cookie("SimpleSAMLCitizenAuthToken", self.login_token, domain="tabulex.test", path="/")
            return response
        return web.Response(text="<h2>Der skete en fejl</h2><p>Sporings-ID: 8b506243b6</p>", content_type="text/html", status=500)

    async def _portal(self, request: web.Request) -> web.StreamResponse:
        sent: dict[str, str] = {}
        for part in request.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            sent[name] = value
        if "FedAuth" in sent and sent["FedAuth"] != self.portal_session:
            error = "The input is not a valid Base-64 string as it contains a non-base 64 character."
            return web.Response(text=f"<title>{error}</title><h1>Server Error in '/' Application.</h1>", content_type="text/html", status=500)
        signed_in = sent.get("FedAuth") == self.portal_session
        if request.method == "POST" and request.path == "/":
            form = await request.post()
            if form.get("wa") != "wsignin1.0" or form.get("wresult") != self.assertion:
                return web.Response(status=400)
            response = web.Response(status=302, headers={"Location": "/"})
            response.set_cookie("FedAuth", self.portal_session, path="/", httponly=True)
            return response
        if not signed_in:
            return web.Response(status=302, headers={"Location": f"{self._base(self.SP)}{self.PRP}?wa=wsignin1.0&wtrealm={self.portal}"})
        if request.path == "/":
            port = self._base(self.PORTAL).rsplit(":", 1)[1]
            scripts = (
                f'<script src="/scripts/app.js?v={self.portal_session}"></script><script src="/scripts/gone.js"></script>'
                f'<script src="http://{self.PORTAL}:1/closed.js"></script><script src="https://cdn.elsewhere.test/lib.js"></script>'
                f'<script src="http://{self.PORTAL}:{port}/scripts/app.js?v={self.portal_session}"></script><script>var signedIn = true;</script>'
                f'<script src="http://{self.CDN}:{port}/lib.js"></script>'
            )
            page = web.Response(text=f"<html><head><title>Tabulex</title>{scripts}</head><body><p>Fravær for Alma</p></body></html>", content_type="text/html")
            if self.xsrf_cookie:
                page.set_cookie("XSRF-TOKEN", quote(self.xsrf, safe=""), path="/")
            return page
        if request.path.startswith(("/api/PersonsAdgangTilBoern", "/api/Fravaer/")):
            return await self._absence(request)
        if request.path == "/scripts/app.js":
            return web.Response(text=self.SCRIPT, content_type="application/javascript")
        if request.path == "/scripts/chunk.js":
            return web.Response(text=self.CHUNK, content_type="text/javascript")
        if request.path == "/api/children":
            body = [{"childId": 7713, "name": "Alma Hansen", "absenceType": "Sygdom", "present": False, "note": None}]
            return web.json_response(body)
        if request.path == "/api/children/7713/absence":
            return web.json_response([{"date": "2026-11-24", "absenceType": "Sygdom"}])
        if request.path == "/api/settings":
            return web.json_response({"sickReportsEnabled": True})
        if request.path == "/views/fravaer.html":
            return web.Response(
                text='<h2>Meld fravær</h2><form ng-submit="meld()"><input name="fra" type="date"/><select name="aarsag"></select></form>',
                content_type="text/html",
            )
        if request.path == "/api/broken":
            return web.Response(text="{not json", content_type="application/json")
        if request.path == "/api/text":
            return web.Response(text="Alma er syg", content_type="text/plain")
        if request.path == "/api/page":
            return web.Response(text="<title>Fravær</title><h1>Fravær 2026</h1>", content_type="text/html")
        return web.Response(status=404)
