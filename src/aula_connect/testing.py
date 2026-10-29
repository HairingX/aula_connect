"""A simulated Aula, for tests: its login chain - from Aula's OAuth through UniLogin, NemLog-in
and MitID back to Aula's tokens - and its API, each answered as the real one is.

Each step checks what the real one depends on - the cookies set by the steps before it, the
verification token, the SAML responses handed on, the OAuth state and the PKCE verifier - so a
test of a login exercises how the client carries its session, not only its requests. MitID is
`mitid_connect.testing.SimulatedMitID`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from types import TracebackType
from typing import Self
from urllib.parse import urlencode

from aiohttp import web
from aiohttp.test_utils import TestServer
from mitid_connect.testing import SimulatedMitID

from .api.aula_proxy_client import AulaProxyClient
from .login import AulaLoginClient

APP_REDIRECT_URI = "https://app-private.aula.dk"
"""Where Aula sends the app back to, with the code; it is never requested."""


def _form(action: str, fields: dict[str, str], extra: str = "") -> str:
    inputs = "".join(f'<input type="hidden" name="{name}" value="{value}"/>' for name, value in fields.items())
    return f'<html><body><form method="post" action="{action}">{inputs}{extra}</form></body></html>'


class SimulatedAulaLogin:
    """Aula's login chain on a local test server, with a simulated MitID behind it.

    Use it as an async context manager; `client(session, user_id)` then gives a login client
    pointed at it.
    """

    def __init__(self, users: set[str] | None = None, identities: list[str] | None = None) -> None:
        self.mitid = SimulatedMitID(users if users is not None else {"parent"})
        self.identities = identities or []
        """The identities NemLog-in offers to choose between; none, one is taken at once."""
        self.chosen_identity: str | None = None
        self.role_selection = True
        """Whether the broker asks for the role, as it does for a guardian who is also a pupil."""
        self.confirmation_page = True
        """Whether the broker shows its confirmation page before going back to Aula."""
        self.refresh_tokens: dict[str, str] = {}
        """The refresh tokens issued, and the access token each was issued with."""
        self.revoked: set[str] = set()
        self._state = ""
        self._code_challenge = ""
        self._code = ""
        self._verification_token = secrets.token_hex(8)
        self._saml_mitid = secrets.token_hex(8)
        self._saml_aula = secrets.token_hex(8)
        self._server: TestServer | None = None
        self.app = web.Application()
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
                web.get("/api/v22/", self._api_test),
            ]
        )

    async def __aenter__(self) -> Self:
        await self.mitid.__aenter__()
        self._server = TestServer(self.app)
        await self._server.start_server()
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
        client.api_test_base = f"{self.url}/api/v22/"
        return client

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
            raise web.HTTPSeeOther(f"{self.url}/nemlogin/loginoption")
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
            return self._issue()
        verifier = str(form.get("code_verifier", ""))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        if form.get("code") != self._code or challenge != self._code_challenge:
            return web.json_response({"error": "invalid_grant"}, status=400)
        self._code = ""
        return self._issue()

    async def _api_test(self, request: web.Request) -> web.Response:
        token = request.query.get("access_token")
        if token is not None and token not in self.refresh_tokens.values():
            return web.json_response({"status": {"message": "unauthorized"}}, status=401)
        return web.json_response({"status": {"code": 0}, "data": {"issued": time.time()}})


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

    VERSION = 23

    def __init__(self, access_token: str = "access") -> None:
        self.access_token = access_token
        self.csrf_token = secrets.token_hex(8)
        self.widgets = ["0001", "0004", "0029"]
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
        self.birthdays: list[dict[str, object]] = []
        self.weekly_plans: list[dict[str, object]] = []
        self.easyiq_events: list[dict[str, object]] = []
        self.newsletters: list[dict[str, object]] = []
        self.widget_tokens: set[str] = set()
        self.requests: list[str] = []
        """The Aula API methods and widget paths asked for, in order."""
        self._server: TestServer | None = None
        self.app = web.Application()
        self.app.add_routes(
            [
                web.get(f"/api/v{self.VERSION}", self._api),
                web.post(f"/api/v{self.VERSION}", self._api),
                web.get("/meebook/relatedweekplan/all", self._meebook),
                web.post("/easyiq/weekplaninfo", self._easyiq),
                web.get("/minuddannelse/ugebrev", self._minuddannelse),
            ]
        )

    async def __aenter__(self) -> Self:
        self._server = TestServer(self.app)
        await self._server.start_server()
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
        client.meebook_api = f"{self.url}/meebook"
        client.easyiq_api = f"{self.url}/easyiq"
        client.min_uddannelse_api = f"{self.url}/minuddannelse"
        return client

    @staticmethod
    def _ok(data: object) -> web.Response:
        return web.json_response({"status": {"code": 0, "message": "OK"}, "data": data, "version": SimulatedAulaApi.VERSION})

    def _widget_token_valid(self, request: web.Request) -> bool:
        authorization = request.headers.get("Authorization", "")
        return authorization.startswith("Bearer ") and authorization.removeprefix("Bearer ") in self.widget_tokens

    async def _api(self, request: web.Request) -> web.Response:
        if request.query.get("access_token") != self.access_token:
            return web.json_response({"status": {"code": 448, "message": "Unauthorized"}}, status=401)
        if request.method == "POST" and request.headers.get("csrfp-token") != self.csrf_token:
            return web.json_response({"status": {"code": 403, "message": "CSRF"}}, status=403)
        method = request.query.get("method", "")
        self.requests.append(method)
        match method:
            case "profiles.getProfilesByLogin":
                profile = {
                    **self.guardian,
                    "children": [self.child],
                    "institutionProfiles": [self.institution],
                }
                response = self._ok({"profiles": [profile]})
                response.set_cookie("Csrfp-Token", self.csrf_token)
                return response
            case "profiles.getProfileContext":
                widgets = [{"id": index, "widget": {"widgetId": widget, "name": widget, "id": index}} for index, widget in enumerate(self.widgets)]
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
                return self._ok(self.daily_overviews)
            case "messaging.getThreads":
                return self._ok({"moreMessagesExist": False, "page": 0, "threads": self.threads})
            case "messaging.getMessagesForThread":
                return self._ok({"messages": self.messages.get(int(request.query["threadId"]), [])})
            case "notifications.getNotificationsForActiveProfile":
                return self._ok(self.notifications)
            case "calendar.getEventsByProfileIdsAndResourceIds":
                return self._ok(self.events)
            case "calendar.getBirthdayEventsForInstitutions":
                return self._ok(self.birthdays)
            case "aulaToken.getAulaToken":
                token = _jwt()
                self.widget_tokens.add(token)
                return self._ok(token)
            case _:
                return web.json_response({"status": {"code": 404, "message": f"Unknown method {method}"}}, status=404)

    async def _meebook(self, request: web.Request) -> web.Response:
        self.requests.append("meebook")
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
