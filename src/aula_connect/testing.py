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
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from types import TracebackType
from typing import Any, Self, cast
from urllib.parse import urlencode

from aiohttp import web
from aiohttp.test_utils import TestServer
from mitid_connect.testing import Network, SimulatedMitID, User

from .api.aula_proxy_client import AulaProxyClient
from .login import AulaLoginClient

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
                        "institutions": [{"children": [{"id": self.child["id"], "userId": self.child["userId"]}]}],
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
