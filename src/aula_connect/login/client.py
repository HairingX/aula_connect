"""The login to Aula through MitID: Aula's OAuth 2.0 with PKCE, through UniLogin's broker and
NemLog-in to MitID and back, ending in Aula's access and refresh tokens."""

from __future__ import annotations

import base64
import binascii
import hashlib
import inspect
import json
import logging
import secrets
import time
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypedDict, cast
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup, Tag
from mitid_connect import BrowserClient
from mitid_connect.browser_client import MITID_URL

from ..http import REDIRECTS, HttpResponse, HttpSession
from ..redact import redact
from .exceptions import (
    AulaAuthenticationError,
    MitIDError,
    NetworkError,
    OAuthError,
    SAMLError,
    TokenExpiredError,
)

if TYPE_CHECKING:
    import qrcode

BROWSER_HEADERS = {
    # The Aula app's own browser, as its traffic shows.
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; sdk_gphone64_x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Google Chrome";v="113", "Chromium";v="113", "Not-A.Brand";v="24"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
}
"""Headers sent with every request of the login."""

MAX_REDIRECTS = 10
"""The most redirects a step of the login follows before it gives up."""

IdentitySelector = Callable[[list[str]], str | int | Awaitable[str | int]]
"""Chooses one of the MitID identities named, by its number counted from 1."""


class MitIDPage(TypedDict):
    """NemLog-in's MitID page, reached through Aula and UniLogin."""

    verification_token: str
    mitid_url: str
    session_cookies: dict[str, str]


class SamlResponse(TypedDict):
    """The SAML response NemLog-in hands on to UniLogin's broker."""

    relay_state: str
    saml_response: str
    completion_url: str


class BrokerSamlResponse(TypedDict):
    """The SAML response UniLogin's broker hands on to Aula, and where to."""

    final_saml_response: str
    final_relay_state: str
    form_action: str


def _oauth_error(response: HttpResponse) -> str | None:
    """The OAuth 2.0 error code of an error response, None if it has none."""
    try:
        body = response.json()
    except ValueError:
        return None
    error = cast(dict[str, object], body).get("error") if isinstance(body, dict) else None
    return error if isinstance(error, str) else None


def _tag(found: object) -> Tag | None:
    """The element found, None where nothing or only text was."""
    return found if isinstance(found, Tag) else None


def _attribute(tag: Tag | None, name: str) -> str:
    """The value of the attribute `name`, empty where the element or the attribute is missing."""
    value = tag.get(name) if tag is not None else None
    if value is None:
        return ""
    return value if isinstance(value, str) else " ".join(value)


def _form_fields(form: Tag) -> dict[str, str]:
    """The named inputs of a form, with their values."""
    fields: dict[str, str] = {}
    for field in form.find_all("input"):
        name = _attribute(_tag(field), "name")
        if name:
            fields[name] = _attribute(_tag(field), "value")
    return fields


class AulaLoginClient:
    """A login to Aula through MitID, with the MitID app or a code token, and its tokens.

    Example:
        client = AulaLoginClient(session, mitid_username="username")
        result = await client.authenticate()
        tokens = result["tokens"]
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        mitid_username: str,
        mitid_password: str | None = None,
        mitid_token: str | None = None,
        auth_method: str = "APP",
        timeout: int = 30,
        debug: bool = False,
        verbose: bool = False,
    ) -> None:
        """Prepare a login, sending nothing yet.

        Args:
            session: The aiohttp session to log in on. Its cookies are the login's, so it is
                one for this login alone.
            mitid_username: The MitID user ID.
            mitid_password: The MitID password, for the code token.
            mitid_token: The code token's current digits.
            auth_method: "APP" for the MitID app, "TOKEN" for the code token and password.
            timeout: Seconds a single request may take.
            debug: Log the login's steps in detail too, when verbose.
            verbose: Log the login's steps, not only its warnings and errors.
        """
        self.session = HttpSession(session, BROWSER_HEADERS, timeout)
        self.mitid_username = mitid_username
        self.mitid_password = mitid_password
        self.mitid_token = mitid_token
        self.auth_method = auth_method
        self.timeout = timeout
        self.debug = debug
        self.verbose = verbose
        self.logger = logging.getLogger(__name__)

        self.auth_base_url = "https://login.aula.dk"
        self.broker_url = "https://broker.unilogin.dk"
        self.nemlogin_url = "https://nemlog-in.mitid.dk"
        self.mitid_url = MITID_URL
        self.app_redirect_uri = "https://app-private.aula.dk"
        self.client_id_level_3 = "_99949a54b8b65423862aac1bf629599ed64231607a"
        self.scope = "aula-sensitive"

        self.identity_selector: IdentitySelector | None = None
        """Chooses between several MitID identities; without one, the first is taken."""
        self.available_identities: list[str] = []
        """The identities MitID offered to choose between, in the last login."""

        self.code_verifier = ""
        self.code_challenge = ""
        self.state = ""
        self.tokens: dict[str, Any] | None = None
        """The tokens of the last login or renewal, with `expires_at` in seconds since the epoch."""
        self.mitid_client: BrowserClient | None = None
        """The MitID login while it runs."""

    def _cookie_header(self, domain: str | None = None) -> dict[str, str]:
        """The session's cookies as a header - those of `domain` and those of no domain, where one is given."""
        cookies = [
            f"{cookie.name}={cookie.value}"
            for cookie in self.session.cookies
            if domain is None or domain in cookie.domain or cookie.domain == ""
        ]
        return {"cookie": "; ".join(cookies)} if cookies else {}

    def log(self, message: str, level: str = "INFO") -> None:
        """Log `message` with its secrets taken out; DEBUG and INFO only when verbose, DEBUG only when debugging too."""
        level = level.upper()
        if level in ("DEBUG", "INFO") and not self.verbose:
            return
        if level == "DEBUG" and not self.debug:
            return
        self.logger.log(logging.getLevelNamesMapping().get(level, logging.INFO), redact(message))

    def generate_pkce_parameters(self) -> tuple[str, str]:
        """A new PKCE code verifier and its S256 code challenge."""
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
        challenge = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        code_challenge = base64.urlsafe_b64encode(challenge).decode("utf-8").rstrip("=")
        return code_verifier, code_challenge

    def generate_state(self) -> str:
        """A new OAuth state."""
        return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("utf-8").rstrip("=")

    async def step1_start_oauth_flow(self) -> str:
        """Start Aula's OAuth authorization, and give the URL it sends the login on to.

        Raises:
            OAuthError: Aula sent the login nowhere.
            NetworkError: Aula could not be reached.
        """
        self.log("Starting OAuth 2.0 authorization flow")
        self.code_verifier, self.code_challenge = self.generate_pkce_parameters()
        self.state = self.generate_state()
        auth_params = {
            "response_type": "code",
            "client_id": self.client_id_level_3,
            "scope": self.scope,
            "redirect_uri": self.app_redirect_uri,
            "state": self.state,
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
        }
        url = f"{self.auth_base_url}/simplesaml/module.php/oidc/authorize.php?{urllib.parse.urlencode(auth_params)}"
        try:
            response = await self.session.get(url, allow_redirects=False)
        except (aiohttp.ClientError, TimeoutError) as e:
            raise NetworkError(f"Network error during OAuth flow: {redact(e)}") from e
        self.log(f"OAuth authorization response: {response.status_code}", "DEBUG")

        if response.status_code in REDIRECTS and "Location" in response.headers:
            return response.headers["Location"]
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            action = _attribute(_tag(soup.find("form")), "action")
            if action:
                return action
            refresh = _attribute(_tag(soup.find("meta", {"http-equiv": "refresh"})), "content")
            if "url=" in refresh.lower():
                return refresh[refresh.lower().index("url=") + 4 :]
            raise OAuthError("OAuth authorization endpoint returned 200 but no redirect found")
        raise OAuthError(f"Unexpected OAuth authorization response: {response.status_code}")

    async def step3_follow_redirect_chain(self, start_url: str) -> MitIDPage:
        """Follow Aula's redirects through UniLogin's broker to NemLog-in's MitID page.

        Raises:
            SAMLError: The chain ended anywhere else.
            NetworkError: A step could not be reached.
        """
        self.log("Following redirect chain to MitID")
        current_url = start_url
        try:
            for _ in range(MAX_REDIRECTS):
                response = await self.session.get(current_url, allow_redirects=False)
                if response.status_code in REDIRECTS:
                    if "Location" not in response.headers:
                        raise SAMLError("Redirect response missing Location header")
                    current_url = urljoin(current_url, response.headers["Location"])
                    continue
                if response.status_code != 200:
                    raise SAMLError(f"Unexpected status code: {response.status_code}")
                soup = BeautifulSoup(response.text, "html.parser")
                if "broker.unilogin.dk" in response.url or response.url.startswith(self.broker_url):
                    self.log("Reached UniLogin broker - looking for IdP selection")
                    return await self._handle_broker_page(soup)
                if "mitid.dk" in response.url or "nemlog-in" in response.url or response.url.startswith(self.nemlogin_url):
                    token_input = _tag(soup.find("input", {"name": "__RequestVerificationToken"}))
                    if token_input is None:
                        raise SAMLError("Could not find RequestVerificationToken on MitID page")
                    return {
                        "verification_token": _attribute(token_input, "value"),
                        "mitid_url": response.url,
                        "session_cookies": self.session.cookies.get_dict(),
                    }
                raise SAMLError(f"Unexpected page reached: {redact(response.url)}")
        except (aiohttp.ClientError, TimeoutError) as e:
            raise NetworkError(f"Network error during redirect chain: {redact(e)}") from e
        raise SAMLError(f"Too many redirects ({MAX_REDIRECTS})")

    async def _handle_broker_page(self, soup: BeautifulSoup) -> MitIDPage:
        """Choose NemLog-in on UniLogin's page of identity providers, and go on to MitID."""
        form = _tag(soup.find("form"))
        action = _attribute(form, "action")
        if form is None or not action:
            raise SAMLError("No usable form found on broker page")
        fields = _form_fields(form)
        # The broker has named its choice of identity provider differently over time.
        for selector in ("selectedIdp", "idp", "authMethod", "provider"):
            for value in ("nemlogin3", "mitid", "MitID", "nemlogin"):
                response = await self.session.post(action, data={**fields, selector: value}, allow_redirects=False)
                if response.status_code in REDIRECTS and "Location" in response.headers:
                    return await self.step3_follow_redirect_chain(response.headers["Location"])
        raise SAMLError("Could not find working IdP selection method")

    async def step4_mitid_authentication(self, verification_token: str) -> str:
        """Log in to MitID, and give the authorization code it ends with.

        Raises:
            MitIDError: MitID refused the login, or NemLog-in did not start it.
            NetworkError: NemLog-in could not be reached.
        """
        self.log(f"Starting MitID authentication (method: {self.auth_method})")
        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9,da;q=0.8",
            "cache-control": "no-cache",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "origin": self.nemlogin_url,
            "pragma": "no-cache",
            "referer": f"{self.nemlogin_url}/login/mitid",
            "x-requested-with": "XMLHttpRequest",
        }
        try:
            response = await self.session.post(
                f"{self.nemlogin_url}/login/mitid/initialize",
                headers=headers,
                data={"__RequestVerificationToken": verification_token},
            )
            initialization: object = response.json()
            # NemLog-in answers with the JSON object as a JSON string.
            if isinstance(initialization, str):
                initialization = json.loads(initialization)
            aux_value = cast(dict[str, object], initialization).get("Aux") if isinstance(initialization, dict) else None
            if not isinstance(aux_value, str) or not aux_value:
                raise MitIDError("No Aux value in MitID initialization response")
            aux = json.loads(base64.b64decode(aux_value).decode())
        except (aiohttp.ClientError, TimeoutError) as e:
            raise NetworkError(f"Network error during MitID authentication: {redact(e)}") from e
        except (ValueError, binascii.Error) as e:
            raise MitIDError(f"Invalid MitID response format: {e}") from e

        authorization_code = await self._get_mitid_authentication_code(aux)
        self.log("MitID authentication code obtained")
        self.mitid_client = None
        return authorization_code

    async def _get_mitid_authentication_code(self, aux: Any) -> str:
        """Run the MitID login NemLog-in started with `aux`, and give its authorization code."""
        try:
            client_hash = binascii.hexlify(base64.b64decode(aux["coreClient"]["checksum"])).decode("ascii")
            self.mitid_client = BrowserClient(
                self.session.session,
                client_hash,
                str(aux["parameters"]["authenticationSessionId"]),
                headers=self.session.headers,
                timeout=self.timeout,
                base_url=self.mitid_url,
            )
            await self.mitid_client.start()
            authenticators = await self.mitid_client.identify_as_user_and_get_available_authenticators(
                self.mitid_username
            )
            self.log(f"Chosen method is {self.auth_method}, available authenticators: {list(authenticators)}")
            if self.auth_method == "TOKEN" and "TOKEN" in authenticators:
                if not self.mitid_password:
                    raise MitIDError("MitID password is required for TOKEN authentication method")
                if not self.mitid_token:
                    raise MitIDError("MitID token digits are required for TOKEN authentication method")
                await self.mitid_client.authenticate_with_token(self.mitid_token)
                await self.mitid_client.authenticate_with_password(self.mitid_password)
            elif self.auth_method == "APP" and "APP" in authenticators:
                await self.mitid_client.authenticate_with_app()
            else:
                raise MitIDError(f"Authentication method {self.auth_method} not available")
            return await self.mitid_client.finalize_authentication_and_get_authorization_code()
        except Exception as e:
            raise MitIDError(f"MitID authentication failed: {redact(e)}") from e

    async def step5_complete_mitid_flow(self, verification_token: str, authorization_code: str) -> SamlResponse:
        """Hand MitID's authorization code to NemLog-in, choosing the identity where it asks, and give its SAML response.

        Raises:
            SAMLError: NemLog-in answered with no SAML response.
            MitIDError: The identity chosen is not one offered.
            NetworkError: NemLog-in could not be reached.
        """
        self.log("Completing MitID authentication flow")
        params = {
            "__RequestVerificationToken": verification_token,
            "NewCulture": "",
            "MitIDUseConfirmed": "True",
            "MitIDAuthCode": authorization_code,
            "MitIDAuthenticationCancelled": "",
            "MitIDCoreClientError": "",
            "SessionStorageActiveSessionUuid": self.session.cookies.get("SessionUuid", ""),
            "SessionStorageActiveChallenge": self.session.cookies.get("Challenge", ""),
        }
        try:
            response = await self.session.post(f"{self.nemlogin_url}/login/mitid", data=params)
            self.log(f"MitID completion response: {response.status_code}", "DEBUG")
            soup = BeautifulSoup(response.text, "html.parser")
            if response.url == f"{self.nemlogin_url}/loginoption":
                self.log("Multiple identity options detected, choosing...")
                response, soup = await self._choose_between_multiple_identities(response, soup)
        except (aiohttp.ClientError, TimeoutError) as e:
            raise NetworkError(f"Network error during MitID completion: {redact(e)}") from e

        relay_state = _tag(soup.find("input", {"name": "RelayState"}))
        saml_response = _tag(soup.find("input", {"name": "SAMLResponse"}))
        if relay_state is None:
            raise SAMLError("Could not find RelayState in MitID completion response")
        if saml_response is None:
            raise SAMLError("Could not find SAMLResponse in MitID completion response")
        return {
            "relay_state": _attribute(relay_state, "value"),
            "saml_response": _attribute(saml_response, "value"),
            "completion_url": response.url,
        }

    async def _choose_between_multiple_identities(
        self, response: HttpResponse, soup: BeautifulSoup
    ) -> tuple[HttpResponse, BeautifulSoup]:
        """Choose one of the identities NemLog-in offers, and give its answer."""
        data: dict[str, str] = {}
        form = soup.select_one("form")
        inputs: list[Tag] = form.select("input") if form is not None else []
        for found in inputs:
            key = _attribute(found, "name") or _attribute(found, "id")
            if key:
                data[key] = _attribute(found, "value")
        session_uuid = self.session.cookies.get("SessionUuid", "")
        challenge = self.session.cookies.get("Challenge", "")
        if session_uuid:
            data["SessionStorageActiveSessionUuid"] = session_uuid
        if challenge:
            data["SessionStorageActiveChallenge"] = challenge

        options = [option for option in (_tag(found) for found in soup.select("a.list-link")) if option is not None]
        names = [option.select_one("div.list-link-text") for option in options]
        self.available_identities = [name.get_text() if name is not None else "" for name in names]

        if self.identity_selector is not None:
            chosen = self.identity_selector(self.available_identities)
            identity = await chosen if inspect.isawaitable(chosen) else chosen
        else:
            identity = 1
        try:
            selected = options[int(identity) - 1] if int(identity) >= 1 else None
        except (ValueError, IndexError):
            selected = None
        if selected is None:
            raise MitIDError("Identity not in list of identities")
        data["ChosenOptionJson"] = _attribute(selected, "data-loginoptions")

        headers = {"Content-Type": "application/x-www-form-urlencoded", "Referer": response.url}
        response = await self.session.post(response.url, data=data, headers=headers)
        return response, BeautifulSoup(response.text, "html.parser")

    async def step6_saml_broker_flow(self, saml_data: SamlResponse) -> BrokerSamlResponse:
        """Hand NemLog-in's SAML response to UniLogin's broker, and give the one it hands on to Aula.

        Raises:
            SAMLError: The broker did not take the response.
            NetworkError: The broker could not be reached.
        """
        self.log("Processing SAML broker flow")
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "accept-language": "en-US,en;q=0.9,da;q=0.8",
            "cache-control": "max-age=0",
            "content-type": "application/x-www-form-urlencoded",
            "origin": self.nemlogin_url,
            "referer": f"{self.nemlogin_url}/login/mitid",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "cross-site",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            **self._cookie_header(),
        }
        params = {"RelayState": saml_data["relay_state"], "SAMLResponse": saml_data["saml_response"]}
        try:
            response = await self.session.post(
                f"{self.broker_url}/auth/realms/broker/broker/nemlogin3/endpoint",
                data=params,
                headers=headers,
                allow_redirects=False,
            )
            if "Location" not in response.headers:
                raise SAMLError("No redirect from broker endpoint")
            return await self._process_broker_response(await self.session.get(response.headers["Location"]))
        except (aiohttp.ClientError, TimeoutError) as e:
            raise NetworkError(f"Network error during SAML broker flow: {redact(e)}") from e

    async def _process_broker_response(self, response: HttpResponse) -> BrokerSamlResponse:
        """Pass the broker's own pages - the role, as a guardian, and its confirmation - and give its SAML response to Aula."""
        soup = BeautifulSoup(response.text, "html.parser")
        form = _tag(soup.find("form"))
        action = _attribute(form, "action")
        # The broker's session is in the page's URL, or else in its form's.
        query = parse_qs(urlparse(response.url).query)
        if not query.get("session_code") or not query.get("execution"):
            query = parse_qs(urlparse(action).query)
        params = {name: query.get(name, [""])[0] for name in ("session_code", "execution", "client_id", "tab_id")}
        if action:
            url = urljoin(response.url, action)
        else:
            url = f"{self.broker_url}/auth/realms/broker/login-actions/post-broker-login?{urllib.parse.urlencode(params)}"
        if not params["session_code"] or not params["execution"]:
            self.log("Missing broker session parameters", "WARNING")

        fields = _form_fields(form) if form is not None else {}
        # A guardian who is also a pupil is asked which role to log in as.
        if "selected-aktoer" in fields:
            fields["selected-aktoer"] = "KONTAKT"

        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "content-type": "application/x-www-form-urlencoded",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "upgrade-insecure-requests": "1",
        }
        response = await self.session.post(url, headers={**headers, **self._cookie_header()}, data=fields, allow_redirects=False)
        self.log(f"Post-broker response status: {response.status_code}", "DEBUG")

        if response.status_code == 200:
            button = _tag(BeautifulSoup(response.text, "html.parser").find("button", {"id": "confirmation-button"}))
            confirmation = _tag(button.find_parent("form")) if button is not None else None
            confirm_action = _attribute(confirmation, "action")
            if confirmation is not None and confirm_action:
                self.log("Found intermediate confirmation page (UniLogin success), submitting...")
                response = await self.session.post(
                    urljoin(response.url, confirm_action),
                    headers={**headers, **self._cookie_header()},
                    data=_form_fields(confirmation),
                    allow_redirects=False,
                )

        if "Location" not in response.headers:
            raise SAMLError(f"No redirect from post-broker-login (status={response.status_code})")
        after = await self.session.get(response.headers["Location"])
        saml_form = _tag(BeautifulSoup(after.text, "html.parser").find("form"))
        if saml_form is None:
            raise SAMLError("No SAML form found in broker response")
        saml_response = _tag(saml_form.find("input", {"name": "SAMLResponse"}))
        if saml_response is None:
            raise SAMLError("Could not find SAMLResponse - this is critical")
        return {
            "final_saml_response": _attribute(saml_response, "value"),
            "final_relay_state": _attribute(_tag(saml_form.find("input", {"name": "RelayState"})), "value"),
            "form_action": _attribute(saml_form, "action"),
        }

    async def step7_complete_aula_login(self, saml_data: BrokerSamlResponse) -> str:
        """Hand the broker's SAML response to Aula, and give the OAuth callback URL Aula ends at.

        Raises:
            OAuthError: Aula did not send the login back with a code.
            NetworkError: Aula could not be reached.
        """
        self.log("Completing Aula login with SAML response")
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "null",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "cross-site",
            "upgrade-insecure-requests": "1",
            **self._cookie_header("aula.dk"),
        }
        data = {"SAMLResponse": saml_data["final_saml_response"], "RelayState": saml_data["final_relay_state"]}
        # A form without an action is sent where the browser is, which is Aula's own endpoint.
        endpoint = saml_data["form_action"] or f"{self.auth_base_url}/simplesaml/module.php/saml/sp/saml2-acs.php/uni-sp"
        try:
            response = await self.session.post(endpoint, headers=headers, data=data, allow_redirects=False)
            if "Location" not in response.headers:
                raise OAuthError("No redirect from Aula SAML endpoint")
            return await self._follow_oauth_callback_redirects(urljoin(response.url, response.headers["Location"]))
        except (aiohttp.ClientError, TimeoutError) as e:
            raise NetworkError(f"Network error during Aula login completion: {redact(e)}") from e

    async def _follow_oauth_callback_redirects(self, start_url: str) -> str:
        """Follow Aula's redirects up to the app's callback URL, with its code or its error, which is never requested."""
        url = start_url
        for _ in range(MAX_REDIRECTS):
            if url.startswith(self.app_redirect_uri):
                return url
            response = await self.session.get(url, allow_redirects=False)
            if response.status_code in REDIRECTS and "Location" in response.headers:
                url = urljoin(response.url, response.headers["Location"])
                continue
            raise OAuthError(
                f"Did not receive OAuth callback URL: {response.status_code} at {redact(response.url)}"
            )
        raise OAuthError(f"Too many redirects ({MAX_REDIRECTS}) without finding OAuth callback")

    async def step8_exchange_oauth_code(self, callback_url: str) -> dict[str, Any]:
        """Exchange the authorization code of the callback URL for Aula's tokens, and keep them.

        Raises:
            OAuthError: The URL has no code, or the wrong state, or Aula refused the code.
            NetworkError: Aula could not be reached.
        """
        self.log("Exchanging OAuth authorization code for tokens")
        query = parse_qs(urlparse(callback_url).query)
        if "code" not in query:
            raise OAuthError("No authorization code in callback URL")
        if "state" in query and query["state"][0] != self.state:
            raise OAuthError("State parameter mismatch")
        token_data = {
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "client_id": self.client_id_level_3,
            "redirect_uri": self.app_redirect_uri,
            "code_verifier": self.code_verifier,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        try:
            response = await self.session.post(
                f"{self.auth_base_url}/simplesaml/module.php/oidc/token.php", data=token_data, headers=headers
            )
        except (aiohttp.ClientError, TimeoutError) as e:
            raise NetworkError(f"Network error during token exchange: {redact(e)}") from e
        if response.status_code != 200:
            raise OAuthError(f"Token exchange failed: {response.status_code} - {redact(response.text)}")
        try:
            tokens = response.json()
        except ValueError:
            tokens = None
        if not isinstance(tokens, dict):
            raise OAuthError("Invalid token response format: no JSON object")
        tokens = cast(dict[str, Any], tokens)
        if "expires_in" in tokens:
            tokens["expires_at"] = time.time() + tokens["expires_in"]
        self.tokens = tokens
        self.log(f"Token exchange successful, access token expires in {tokens.get('expires_in', 'unknown')} seconds")
        return tokens

    async def renew_access_token(self) -> bool:
        """Renew the access token with the refresh token.

        Returns:
            Whether it was renewed; False also where Aula answered in a way the renewal does not
            know, which may pass.

        Raises:
            NetworkError: Aula could not be reached, or answered with a server error.
            TokenExpiredError: Aula no longer accepts the refresh token; only a new login helps.
        """
        if not self.tokens or "refresh_token" not in self.tokens:
            self.log("No refresh token available for renewal", "ERROR")
            return False
        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": self.tokens["refresh_token"],
            "client_id": self.client_id_level_3,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": self.session.headers["User-Agent"],
        }
        try:
            response = await self.session.post(
                f"{self.auth_base_url}/simplesaml/module.php/oidc/token.php", data=token_data, headers=headers
            )
        except (aiohttp.ClientError, TimeoutError, OSError) as e:
            self.log(f"Network error during token renewal: {e}", "ERROR")
            raise NetworkError(f"Network error during token refresh: {redact(e)}") from e

        if response.status_code in (401, 403):
            self.log(f"Refresh token rejected (HTTP {response.status_code}). Re-authentication required.", "ERROR")
            raise TokenExpiredError(f"Refresh token rejected by server (HTTP {response.status_code})")
        if response.status_code == 400 and _oauth_error(response) == "invalid_grant":
            # OAuth 2.0 (RFC 6749, 5.2) answers 400 invalid_grant for a refresh token that is
            # invalid, expired or revoked: only a new login helps.
            self.log("Refresh token no longer valid. Re-authentication required.", "ERROR")
            raise TokenExpiredError("Refresh token rejected by server (invalid_grant)")
        if response.status_code >= 500 or response.status_code == 429:
            self.log(f"Token renewal transient error (HTTP {response.status_code}). Will retry.", "WARNING")
            raise NetworkError(f"Token endpoint returned transient error (HTTP {response.status_code})")
        if response.status_code != 200:
            self.log(f"Token renewal failed: {response.status_code} - {response.text}", "ERROR")
            return False

        try:
            renewed = response.json()
        except ValueError:
            renewed = None
        if not isinstance(renewed, dict) or "access_token" not in renewed:
            self.log("Token response missing access_token field", "ERROR")
            return False
        renewed = cast(dict[str, Any], renewed)
        self.tokens["access_token"] = renewed["access_token"]
        if "refresh_token" in renewed:
            self.tokens["refresh_token"] = renewed["refresh_token"]
        if "expires_in" in renewed:
            self.tokens["expires_in"] = renewed["expires_in"]
            self.tokens["expires_at"] = time.time() + renewed["expires_in"]
        self.log(f"Token renewed, expires in {renewed.get('expires_in', 'unknown')} seconds")
        return True

    async def authenticate(self) -> dict[str, Any]:
        """Log in to Aula through MitID.

        Returns:
            `success`, True, and the `tokens`.

        Raises:
            AulaAuthenticationError: A step of the login failed; NetworkError, one of its kinds,
                where a step could not be reached.
        """
        self.log("Starting Aula login")
        try:
            saml_redirect_url = await self.step1_start_oauth_flow()
            mitid_page = await self.step3_follow_redirect_chain(saml_redirect_url)
            auth_code = await self.step4_mitid_authentication(mitid_page["verification_token"])
            saml_response = await self.step5_complete_mitid_flow(mitid_page["verification_token"], auth_code)
            broker_response = await self.step6_saml_broker_flow(saml_response)
            callback_url = await self.step7_complete_aula_login(broker_response)
            tokens = await self.step8_exchange_oauth_code(callback_url)
        except AulaAuthenticationError as e:
            self.log(f"Authentication flow failed: {e}", "ERROR")
            raise
        except Exception as e:
            self.log(f"Authentication flow failed: {e}", "ERROR")
            raise AulaAuthenticationError(f"Authentication failed: {redact(e)}") from e
        self.log("Aula login completed")
        return {"success": True, "tokens": tokens}

    def get_mitid_client(self) -> BrowserClient | None:
        """The MitID login while it runs, None otherwise."""
        return self.mitid_client

    def get_qr_codes_svg(self) -> tuple[str, str] | None:
        """The two QR codes MitID shows in turn for the app to scan, as SVG; None while it shows none."""
        qr_codes = self.mitid_client.get_current_qr_codes() if self.mitid_client is not None else None
        if not qr_codes:
            return None
        return self._qr_to_svg(qr_codes[0]), self._qr_to_svg(qr_codes[1])

    @staticmethod
    def _qr_to_svg(qr_code: qrcode.QRCode[Any]) -> str:
        """A QR code as SVG, one unit a module."""
        matrix = qr_code.get_matrix()
        size = len(matrix)
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size * 10}" height="{size * 10}" viewBox="0 0 {size} {size}">',
            '<rect width="100%" height="100%" fill="white"/>',
        ]
        for y, row in enumerate(matrix):
            for x, cell in enumerate(row):
                if cell:
                    parts.append(f'<rect x="{x}" y="{y}" width="1" height="1" fill="black"/>')
        parts.append("</svg>")
        return "".join(parts)

    @property
    def access_token(self) -> str | None:
        """The access token, None before a login."""
        return self.tokens.get("access_token") if self.tokens else None

    @property
    def refresh_token(self) -> str | None:
        """The refresh token, None before a login."""
        return self.tokens.get("refresh_token") if self.tokens else None

    def is_authenticated(self) -> bool:
        """Whether there is an access token."""
        return bool(self.tokens and self.tokens.get("access_token"))
