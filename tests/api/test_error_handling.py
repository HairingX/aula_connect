"""Tests for error handling and 401 retry logic.

Verifies the core safety property: transient errors must NOT trigger MitID
re-authentication (AulaCredentialError / ConfigEntryAuthFailed), while genuine
credential failures MUST still trigger it.
"""
import asyncio
import base64
import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, Mock, patch

import aiohttp
from multidict import CIMultiDict, CIMultiDictProxy

from aula_connect.api.aula_errors import AulaApiError, AulaCredentialError
from aula_connect.api.aula_proxy_client import RECOVERY_COOLDOWN, AulaProxyClient, _decode_jwt_exp
from aula_connect.api.models.aula_profile_models import (
    AulaChildProfile,
    AulaLoginData,
    AulaToken,
    AulaWidget,
)
from aula_connect.api.models.constants import AulaWidgetId
from aula_connect.client import AulaClient
from aula_connect.http import HttpResponse, SentRequest
from aula_connect.login.exceptions import NetworkError, TokenExpiredError

PROXY_LOGGER = "aula_connect.api.aula_proxy_client"


def _make_response(status_code: int, json_body: object = None, text: str = "") -> HttpResponse:
    """Build a response with a given status code and a JSON body, a text body, or none."""
    content = json.dumps(json_body).encode() if json_body is not None else text.encode()
    return HttpResponse(
        status_code=status_code,
        reason=HTTPStatus(status_code).phrase,
        url="https://example.com/api",
        headers=CIMultiDictProxy(CIMultiDict[str]()),
        content=content,
        encoding="utf-8",
        request=SentRequest("GET", "https://example.com/api"),
    )


def _make_proxy() -> AulaProxyClient:
    """A proxy client whose session is a stand-in, reached only through patched methods."""
    client = AulaProxyClient(MagicMock(), "test-token")
    client._apiurl = "https://example.com/api/v1"
    return client


def _make_jwt(exp_timestamp: int | None) -> str:
    """Build a fake JWT with the given exp claim (or no exp). Signature is dummy."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b'=').decode()
    claims = {"exp": exp_timestamp} if exp_timestamp is not None else {}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b'=').decode()
    return f"{header}.{payload}.dummy"


def _fresh_jwt() -> str:
    return _make_jwt(int(time.time()) + 3600)


# ---------------------------------------------------------------------------
# _retry_on_401
# ---------------------------------------------------------------------------

class TestRetryOn401(unittest.TestCase):
    """Tests for AulaProxyClient._retry_on_401."""

    def setUp(self):
        self.client = AulaProxyClient(MagicMock(), "test-token")

    def test_successful_retry_after_transient_401(self):
        """Transient 401 → refresh succeeds → retry returns 200."""
        callback = AsyncMock(return_value=True)
        request_fn = AsyncMock(return_value=_make_response(200, {"data": []}))

        self.client.set_token_refresh_callback(callback)
        result = asyncio.run(self.client._retry_on_401(_make_response(401), request_fn))

        assert result is not None
        self.assertEqual(result.status_code, 200)
        callback.assert_awaited_once()
        request_fn.assert_awaited_once()

    def test_callback_returns_false_raises_connection_error(self):
        """Transient refresh failure → raises ConnectionError (not reauth)."""
        request_fn = AsyncMock()

        self.client.set_token_refresh_callback(AsyncMock(return_value=False))
        with self.assertRaises(ConnectionError):
            asyncio.run(self.client._retry_on_401(_make_response(401), request_fn))
        request_fn.assert_not_called()

    def test_no_callback_set(self):
        """No callback → returns original response unchanged."""
        resp_401 = _make_response(401)
        result = asyncio.run(self.client._retry_on_401(resp_401, AsyncMock()))
        self.assertIs(result, resp_401)

    def test_non_401_passes_through(self):
        """Non-401 responses are returned unchanged without invoking callback."""
        resp_500 = _make_response(500)
        callback = AsyncMock()
        self.client.set_token_refresh_callback(callback)

        result = asyncio.run(self.client._retry_on_401(resp_500, AsyncMock()))

        self.assertIs(result, resp_500)
        callback.assert_not_called()

    def test_none_response_passes_through(self):
        result = asyncio.run(self.client._retry_on_401(None, AsyncMock()))
        self.assertIsNone(result)

    def test_retry_network_error_raises_connection_error(self):
        """If the retry request fails with a network error, raise ConnectionError (not reauth)."""
        request_fn = AsyncMock(side_effect=aiohttp.ClientConnectionError("conn error"))

        self.client.set_token_refresh_callback(AsyncMock(return_value=True))
        with self.assertRaises(ConnectionError):
            asyncio.run(self.client._retry_on_401(_make_response(401), request_fn))

    def test_retry_timeout_raises_connection_error(self):
        """If the retry request times out, raise ConnectionError (not reauth)."""
        request_fn = AsyncMock(side_effect=TimeoutError("timeout"))

        self.client.set_token_refresh_callback(AsyncMock(return_value=True))
        with self.assertRaises(ConnectionError):
            asyncio.run(self.client._retry_on_401(_make_response(401), request_fn))

    def test_retry_still_401_raises_connection_error(self):
        """If retry also returns 401, raise ConnectionError — token was just refreshed so this is transient."""
        request_fn = AsyncMock(return_value=_make_response(401))

        self.client.set_token_refresh_callback(AsyncMock(return_value=True))
        with self.assertRaises(ConnectionError):
            asyncio.run(self.client._retry_on_401(_make_response(401), request_fn))

    def test_retry_non_401_error_returned(self):
        """If retry returns a non-401 error (e.g. 500), return it for normal error handling."""
        request_fn = AsyncMock(return_value=_make_response(500))

        self.client.set_token_refresh_callback(AsyncMock(return_value=True))
        result = asyncio.run(self.client._retry_on_401(_make_response(401), request_fn))
        assert result is not None
        self.assertEqual(result.status_code, 500)

    def test_callback_credential_error_propagates(self):
        """AulaCredentialError from callback propagates (triggers reauth)."""
        callback = AsyncMock(side_effect=AulaCredentialError("expired"))

        self.client.set_token_refresh_callback(callback)
        with self.assertRaises(AulaCredentialError):
            asyncio.run(self.client._retry_on_401(_make_response(401), AsyncMock()))


# ---------------------------------------------------------------------------
# _raise_error
# ---------------------------------------------------------------------------

class TestRaiseError(unittest.TestCase):
    """Tests for AulaProxyClient._raise_error."""

    def test_401_raises_credential_error(self):
        resp = _make_response(401, {"status": {"message": "Unauthorized"}})
        with self.assertRaises(AulaCredentialError):
            AulaProxyClient._raise_error(resp)

    def test_402_raises_permission_error(self):
        with self.assertRaises(PermissionError):
            AulaProxyClient._raise_error(_make_response(402))

    def test_403_raises_permission_error(self):
        with self.assertRaises(PermissionError):
            AulaProxyClient._raise_error(_make_response(403))

    def test_500_raises_api_error_not_credential(self):
        """Server errors must raise AulaApiError, NOT AulaCredentialError."""
        with self.assertRaises(AulaApiError) as ctx:
            AulaProxyClient._raise_error(_make_response(500))
        self.assertNotIsInstance(ctx.exception, AulaCredentialError)

    def test_404_raises_api_error(self):
        with self.assertRaises(AulaApiError):
            AulaProxyClient._raise_error(_make_response(404))

    def test_none_response_noop(self):
        AulaProxyClient._raise_error(None)

    def test_ok_response_noop(self):
        AulaProxyClient._raise_error(_make_response(200))

    def test_malformed_json_uses_fallback_message(self):
        resp = _make_response(500, text="<html>error</html>")
        with self.assertRaises(AulaApiError) as ctx:
            AulaProxyClient._raise_error(resp)
        self.assertIn("500", str(ctx.exception))


# ---------------------------------------------------------------------------
# _refresh_token data validation
# ---------------------------------------------------------------------------

class TestRefreshTokenValidation(unittest.TestCase):
    """Tests for widget token data type validation in _refresh_token."""

    def setUp(self):
        self.client = _make_proxy()

    def _refresh(self, response: HttpResponse | None = None, error: BaseException | None = None,
                 force: bool = True) -> AulaToken | None:
        get = AsyncMock(return_value=response, side_effect=error)
        with patch.object(self.client._session, "get", get):
            return asyncio.run(self.client._refresh_token(AulaWidgetId.WEEKPLAN_PARENTS, force=force))

    def test_valid_string_token(self):
        """String JWT data → creates proper AulaToken."""
        token = self._refresh(_make_response(200, {"data": "some-jwt-token"}))
        assert token is not None
        self.assertEqual(token.bearer_token, "Bearer some-jwt-token")

    def test_force_dict_data_raises(self):
        """force=True + dict data → raises AulaApiError (never returns stale garbage)."""
        with self.assertRaises(AulaApiError):
            self._refresh(_make_response(200, {"data": {"error": "expired"}}))

    def test_force_none_data_raises(self):
        """force=True + None data → raises AulaApiError."""
        with self.assertRaises(AulaApiError):
            self._refresh(_make_response(200, {"data": None}))

    def test_force_int_data_raises(self):
        """force=True + integer data → raises AulaApiError."""
        with self.assertRaises(AulaApiError):
            self._refresh(_make_response(200, {"data": 12345}))

    def test_force_http_error_raises(self):
        """force=True + non-200 → raises AulaApiError (never silently returns stale token)."""
        with self.assertRaises(AulaApiError):
            self._refresh(_make_response(500))

    def test_force_network_error_raises(self):
        """force=True + network error → raises AulaApiError (never silently returns stale token)."""
        with self.assertRaises(AulaApiError):
            self._refresh(error=TimeoutError("timeout"))

    def test_force_failure_clears_stale_cached_token(self):
        """force=True + failure → removes the stale token from the cache so the next poll starts fresh."""
        stale = AulaToken(bearer_token="Bearer stale", timestamp=datetime.now(timezone.utc) - timedelta(hours=1))
        self.client._tokens[AulaWidgetId.WEEKPLAN_PARENTS] = stale

        with self.assertRaises(AulaApiError):
            self._refresh(_make_response(500))
        self.assertNotIn(AulaWidgetId.WEEKPLAN_PARENTS, self.client._tokens)

    def test_non_force_http_error_returns_old_token(self):
        """force=False + non-200 → returns previously cached token (graceful degradation for non-critical refresh)."""
        # Older than 5 min, so a non-forced refresh does go to the endpoint
        previous = AulaToken(bearer_token="Bearer prev", timestamp=datetime.now(timezone.utc) - timedelta(minutes=10))
        self.client._tokens[AulaWidgetId.WEEKPLAN_PARENTS] = previous

        token = self._refresh(_make_response(500), force=False)
        self.assertIs(token, previous)
        self.assertIs(self.client._tokens[AulaWidgetId.WEEKPLAN_PARENTS], previous)

    def test_non_force_network_error_returns_old_token(self):
        """force=False + network error → returns previously cached token (graceful degradation)."""
        previous = AulaToken(bearer_token="Bearer prev", timestamp=datetime.now(timezone.utc) - timedelta(minutes=10))
        self.client._tokens[AulaWidgetId.WEEKPLAN_PARENTS] = previous

        token = self._refresh(error=TimeoutError("timeout"), force=False)
        self.assertIs(token, previous)


# ---------------------------------------------------------------------------
# JWT exp decoding, _get_token caching and full recovery
# ---------------------------------------------------------------------------

class TestJwtExpDecoding(unittest.TestCase):
    """Tests for _decode_jwt_exp, _get_token caching, reset_session and _full_recovery."""

    def test_decode_valid_jwt_exp(self):
        """Valid JWT with exp claim is decoded to UTC datetime."""
        future = int(time.time()) + 3600
        result = _decode_jwt_exp(_make_jwt(future))
        assert result is not None
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(int(result.timestamp()), future)

    def test_decode_jwt_without_exp_returns_none(self):
        self.assertIsNone(_decode_jwt_exp(_make_jwt(None)))

    def test_decode_malformed_jwt_returns_none(self):
        self.assertIsNone(_decode_jwt_exp("not-a-jwt"))
        self.assertIsNone(_decode_jwt_exp("only.two"))
        self.assertIsNone(_decode_jwt_exp(""))

    def test_decode_jwt_exp_in_milliseconds_returns_none(self):
        """Some broken issuers use ms instead of seconds. Reject to avoid caching forever."""
        ms_timestamp = (int(time.time()) + 3600) * 1000
        self.assertIsNone(_decode_jwt_exp(_make_jwt(ms_timestamp)))

    def test_decode_jwt_exp_negative_returns_none(self):
        self.assertIsNone(_decode_jwt_exp(_make_jwt(-1)))
        self.assertIsNone(_decode_jwt_exp(_make_jwt(0)))

    def test_reset_session_preserves_access_token_and_clears_caches(self):
        """reset_session must drop cookies + widget cache but keep the access_token."""
        session = MagicMock()
        client = AulaProxyClient(session, "test-token")
        client._is_logged_in = True
        client._tokens[AulaWidgetId.WEEKPLAN_PARENTS] = AulaToken(
            bearer_token="Bearer cached",
            timestamp=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )

        client.reset_session()

        session.cookie_jar.clear.assert_called_once_with()
        self.assertEqual(client._session._access_token, "test-token")
        self.assertNotIn(AulaWidgetId.WEEKPLAN_PARENTS, client._tokens)
        # The next login() must warm the new server session again
        self.assertFalse(client._is_logged_in)

    def test_get_token_uses_wallclock_cache_only(self):
        """_get_token uses wall-clock cache only — does NOT validate JWT exp.

        Aula occasionally returns JWTs with broken exp (negative TTL); the widget
        endpoint is the authority on validity, not the client.
        """
        client = _make_proxy()
        cached = AulaToken(
            bearer_token="Bearer cached-but-jwt-expired",
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=10),
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        client._tokens[AulaWidgetId.WEEKPLAN_PARENTS] = cached

        with patch.object(client._session, "get", AsyncMock()) as mock_get:
            result = asyncio.run(client._get_token(AulaWidgetId.WEEKPLAN_PARENTS))
        self.assertIs(result, cached)
        mock_get.assert_not_called()

    def test_full_recovery_cookies_oauth_login_widget_token(self):
        """_full_recovery resets cookies, refreshes OAuth, calls login(), fetches new widget JWT.

        Aula keys the widget JWT on its server session, so cookies and access_token
        must both be rotated before a fresh widget JWT is issued.
        """
        session = MagicMock()
        client = AulaProxyClient(session, "test-token")
        client._apiurl = "https://example.com/api/v1"
        callback = AsyncMock(return_value=True)
        client.set_token_refresh_callback(callback)

        fresh_jwt = _fresh_jwt()
        with patch.object(client, "login", AsyncMock()) as mock_login, \
             patch.object(client._session, "get", AsyncMock(return_value=_make_response(200, {"data": fresh_jwt}))):
            token = asyncio.run(client._full_recovery(AulaWidgetId.WEEKPLAN_PARENTS))

        callback.assert_awaited_once()
        mock_login.assert_awaited_once()
        assert token is not None
        self.assertEqual(token.bearer_token, f"Bearer {fresh_jwt}")
        session.cookie_jar.clear.assert_called_once_with()

    def test_full_recovery_propagates_credential_error(self):
        """If OAuth refresh raises AulaCredentialError, _full_recovery propagates it.

        Genuine credential failure must trigger HA reauth — never swallowed.
        """
        client = _make_proxy()
        client.set_token_refresh_callback(AsyncMock(side_effect=AulaCredentialError("refresh token expired")))

        with self.assertRaises(AulaCredentialError):
            asyncio.run(client._full_recovery(AulaWidgetId.WEEKPLAN_PARENTS))

    def test_full_recovery_continues_when_oauth_refresh_returns_false(self):
        """OAuth refresh returning False (transient) should not block recovery."""
        client = _make_proxy()
        client.set_token_refresh_callback(AsyncMock(return_value=False))

        with patch.object(client, "login", AsyncMock()), \
             patch.object(client._session, "get", AsyncMock(return_value=_make_response(200, {"data": _fresh_jwt()}))):
            with self.assertLogs(PROXY_LOGGER, level="WARNING") as cm:
                token = asyncio.run(client._full_recovery(AulaWidgetId.WEEKPLAN_PARENTS))

        self.assertIsNotNone(token)
        self.assertTrue(any("OAuth access_token refresh returned False" in msg for msg in cm.output))

    def test_is_widget_token_expired_body_detects_expired_message(self):
        """200 OK + {'message': '...expired...'} body must be detected as expired token."""
        resp = _make_response(200, {"message": "JWT-Token expired, please renew."})
        self.assertTrue(AulaProxyClient._is_widget_token_expired_body(resp))

    def test_is_widget_token_expired_body_normal_response_returns_false(self):
        """200 OK + valid widget data must NOT be detected as expired."""
        resp = _make_response(200, [{"week": "2026-W01", "data": "valid"}])
        self.assertFalse(AulaProxyClient._is_widget_token_expired_body(resp))

    def test_is_widget_token_expired_body_non_200_returns_false(self):
        """401/500 must NOT be classified as 'expired body' — they're handled separately."""
        self.assertFalse(AulaProxyClient._is_widget_token_expired_body(_make_response(401, {"message": "expired"})))
        self.assertFalse(AulaProxyClient._is_widget_token_expired_body(_make_response(500)))
        self.assertFalse(AulaProxyClient._is_widget_token_expired_body(None))

    def test_is_widget_token_expired_body_handles_malformed_body(self):
        """Non-JSON or non-dict bodies must not crash."""
        resp = _make_response(200, text="<html>not json</html>")
        self.assertFalse(AulaProxyClient._is_widget_token_expired_body(resp))

    def test_full_recovery_cooldown_skips_when_recent(self):
        """Recovery cooldown must prevent OAuth churn during persistent Aula outages."""
        client = _make_proxy()
        client._last_recovery_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        stale_token = AulaToken(bearer_token="Bearer stale", timestamp=datetime.now(timezone.utc), expires_at=None)
        client._tokens[AulaWidgetId.WEEKPLAN_PARENTS] = stale_token
        callback = AsyncMock(return_value=True)
        client.set_token_refresh_callback(callback)

        with self.assertLogs(PROXY_LOGGER, level="WARNING") as cm:
            result = asyncio.run(client._full_recovery(AulaWidgetId.WEEKPLAN_PARENTS))

        self.assertIs(result, stale_token)
        callback.assert_not_called()
        self.assertTrue(any("Skipping full recovery" in msg for msg in cm.output))

    def test_full_recovery_cooldown_allows_after_window(self):
        """After cooldown window, recovery proceeds normally."""
        client = _make_proxy()
        client._last_recovery_at = datetime.now(timezone.utc) - RECOVERY_COOLDOWN - timedelta(seconds=10)
        client.set_token_refresh_callback(AsyncMock(return_value=True))

        with patch.object(client, "login", AsyncMock()), \
             patch.object(client._session, "get", AsyncMock(return_value=_make_response(200, {"data": _fresh_jwt()}))):
            token = asyncio.run(client._full_recovery(AulaWidgetId.WEEKPLAN_PARENTS))

        self.assertIsNotNone(token)
        last_recovery_at = client._last_recovery_at
        assert last_recovery_at is not None
        self.assertLess((datetime.now(timezone.utc) - last_recovery_at).total_seconds(), 5)

    def test_reset_session_clears_login_result(self):
        """reset_session must clear _login_result so next login() does FULL bootstrap."""
        client = AulaProxyClient(MagicMock(), "test-token")
        client._login_result = AulaLoginData(api_version=19, profiles=[], widgets=[])
        client._is_logged_in = True

        client.reset_session()

        self.assertIsNone(client._login_result)
        self.assertFalse(client._is_logged_in)

    def test_full_recovery_concurrent_calls_serialized(self):
        """Two concurrent _full_recovery calls must serialize via _token_refresh_lock.

        The second caller then sees the cooldown the first one set, so the OAuth
        refresh, session reset and login happen once.
        """
        client = _make_proxy()
        callback_count = 0

        async def slow_callback() -> bool:
            nonlocal callback_count
            callback_count += 1
            await asyncio.sleep(0.05)
            return True
        client.set_token_refresh_callback(slow_callback)

        async def recover_twice() -> None:
            await asyncio.gather(
                client._full_recovery(AulaWidgetId.WEEKPLAN_PARENTS),
                client._full_recovery(AulaWidgetId.WEEKPLAN_PARENTS),
            )

        with patch.object(client, "login", AsyncMock()), \
             patch.object(client._session, "get", AsyncMock(return_value=_make_response(200, {"data": _fresh_jwt()}))):
            asyncio.run(recover_twice())

        self.assertEqual(callback_count, 1)

    def test_full_recovery_continues_when_login_fails(self):
        """If login() fails after reset, still try to fetch widget JWT."""
        client = _make_proxy()
        client.set_token_refresh_callback(AsyncMock(return_value=True))

        with patch.object(client, "login", AsyncMock(side_effect=ConnectionError("network"))), \
             patch.object(client._session, "get", AsyncMock(return_value=_make_response(200, {"data": _fresh_jwt()}))):
            with self.assertLogs(PROXY_LOGGER, level="WARNING") as cm:
                token = asyncio.run(client._full_recovery(AulaWidgetId.WEEKPLAN_PARENTS))

        self.assertIsNotNone(token)
        self.assertTrue(any("login() after session reset failed" in msg for msg in cm.output))

    def test_get_token_refreshes_when_cache_was_cleared(self):
        """A cache emptied by reset_session sends _get_token to a refresh, without a KeyError."""
        client = _make_proxy()
        refreshed = AulaToken(bearer_token="Bearer refreshed", timestamp=datetime.now(timezone.utc))
        client._tokens[AulaWidgetId.WEEKPLAN_PARENTS] = AulaToken(
            bearer_token="Bearer test", timestamp=datetime.now(timezone.utc),
        )
        client.reset_session()

        with patch.object(client, "_refresh_token", AsyncMock(return_value=refreshed)) as refresh:
            result = asyncio.run(client._get_token(AulaWidgetId.WEEKPLAN_PARENTS))

        self.assertIs(result, refreshed)
        refresh.assert_awaited_once_with(AulaWidgetId.WEEKPLAN_PARENTS)

    def test_concurrent_refresh_serialized_by_lock(self):
        """Three concurrent _refresh_token calls → only one HTTP call thanks to lock + double-check."""
        client = _make_proxy()
        new_jwt = _fresh_jwt()
        call_count = 0

        async def slow_get(*args: Any, **kwargs: Any) -> HttpResponse:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return _make_response(200, {"data": new_jwt})

        async def refresh_three_times() -> list[AulaToken | None]:
            return list(await asyncio.gather(
                *(client._refresh_token(AulaWidgetId.WEEKPLAN_PARENTS, force=False) for _ in range(3))
            ))

        with patch.object(client._session, "get", AsyncMock(side_effect=slow_get)):
            results = asyncio.run(refresh_three_times())

        tokens = [token for token in results if token is not None]
        self.assertEqual(len(tokens), 3)
        self.assertTrue(all(token.bearer_token == f"Bearer {new_jwt}" for token in tokens))
        self.assertEqual(call_count, 1, "Lock + double-check should serialize to a single HTTP refresh")

    def test_get_token_uses_wallclock_cache_within_window(self):
        """Cache is used while within TOKEN_EXPIRATION_TIME wall-clock window."""
        client = _make_proxy()
        cached = AulaToken(
            bearer_token="Bearer cached",
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=2),
            expires_at=None,
        )
        client._tokens[AulaWidgetId.WEEKPLAN_PARENTS] = cached

        with patch.object(client._session, "get", AsyncMock()) as mock_get:
            result = asyncio.run(client._get_token(AulaWidgetId.WEEKPLAN_PARENTS))
        self.assertIs(result, cached)
        mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# getAulaToken retry behavior (transient 5xx, network errors, main-session 401)
# ---------------------------------------------------------------------------

class TestGetAulaTokenRetry(unittest.TestCase):
    """Tests that _refresh_token absorbs transient failures of the aulaToken endpoint.

    Without these retries, a single 500 or network blip on Aula's token endpoint
    would either silently return a stale token (non-force) or raise AulaApiError
    (force) — both unnecessary given the failure is usually sub-second.
    """

    def setUp(self):
        self.client = _make_proxy()

    def _force_refresh(self, get: AsyncMock) -> AulaToken | None:
        with patch.object(self.client._session, "get", get):
            return asyncio.run(self.client._refresh_token(AulaWidgetId.WEEKPLAN_PARENTS, force=True))

    def test_transient_5xx_recovers_via_retry(self):
        """500 on first attempt, 200 on second → returns fresh token, no error."""
        jwt = _fresh_jwt()
        get = AsyncMock(side_effect=[_make_response(500, text="transient"), _make_response(200, {"data": jwt})])
        token = self._force_refresh(get)
        assert token is not None
        self.assertEqual(token.bearer_token, f"Bearer {jwt}")

    def test_transient_timeout_recovers_via_retry(self):
        """Timeout on first attempt, 200 on second → returns fresh token."""
        jwt = _fresh_jwt()
        get = AsyncMock(side_effect=[TimeoutError("first attempt times out"), _make_response(200, {"data": jwt})])
        token = self._force_refresh(get)
        assert token is not None
        self.assertEqual(token.bearer_token, f"Bearer {jwt}")

    def test_persistent_5xx_exhausts_retries_and_raises_in_force_mode(self):
        """All attempts 500 → force-mode raises with diagnostic HTTP status."""
        with self.assertRaises(AulaApiError) as ctx:
            self._force_refresh(AsyncMock(return_value=_make_response(500, text="down")))
        self.assertIn("500", str(ctx.exception))

    def test_main_session_401_triggers_callback_and_retries(self):
        """401 from getAulaToken → token-refresh-callback invoked → retry succeeds on fresh session."""
        jwt = _fresh_jwt()
        callback_count = 0

        async def callback() -> bool:
            nonlocal callback_count
            callback_count += 1
            return True
        self.client.set_token_refresh_callback(callback)

        # 401 is not retried by the 5xx loop; only the callback's refresh makes the endpoint answer
        def respond(*args: Any, **kwargs: Any) -> HttpResponse:
            if callback_count == 0:
                return _make_response(401, text="main session expired")
            return _make_response(200, {"data": jwt})

        token = self._force_refresh(AsyncMock(side_effect=respond))

        assert token is not None
        self.assertEqual(token.bearer_token, f"Bearer {jwt}")
        self.assertEqual(callback_count, 1, "main-session refresh callback must have been invoked")

    def test_main_session_401_without_callback_fails_in_force_mode(self):
        """No callback set + 401 → force-mode raises (retry does not rescue)."""
        with self.assertRaises(AulaApiError) as ctx:
            self._force_refresh(AsyncMock(return_value=_make_response(401, text="expired")))
        self.assertIn("401", str(ctx.exception))

    def test_credential_error_from_callback_propagates(self):
        """If main-session refresh raises AulaCredentialError, propagate for reauth."""
        self.client.set_token_refresh_callback(AsyncMock(side_effect=AulaCredentialError("refresh token expired")))

        with self.assertRaises(AulaCredentialError):
            self._force_refresh(AsyncMock(return_value=_make_response(401, text="expired")))


# ---------------------------------------------------------------------------
# End-to-end widget recovery cycle (integration-level)
# ---------------------------------------------------------------------------

def _meebook_login() -> AulaLoginData:
    return AulaLoginData(
        api_version=19,
        profiles=[],
        widgets=[AulaWidget(id=1, name="Meebook", widget_id=AulaWidgetId.WEEKPLAN_PARENTS)],
    )


class TestWidgetRecoveryCycle(unittest.TestCase):
    """End-to-end recovery: widget 401 → force-refresh fails → cache cleared → next poll succeeds.

    Protects the multi-step recovery chain: an AulaApiError swallowed inside a widget
    method, a stale token kept after a failed force-refresh, or _get_token not
    re-fetching on an empty cache each make this test fail.
    """

    def _make_child(self) -> AulaChildProfile:
        return AulaChildProfile(
            first_name="Test",
            id=1,
            institution_code="INST01",
            institution_profile=Mock(),
            main_group=Mock(),
            name="Test Child",
            profile_id=10,
            short_name="T",
            user_id="42",
        )

    def test_full_recovery_cycle_through_get_weekly_plans(self):
        """Poll 1 fails with server-side cascade; Poll 2 succeeds on a clean cache."""
        client = _make_proxy()
        client._login_result = _meebook_login()
        child = self._make_child()
        widgetid = AulaWidgetId.WEEKPLAN_PARENTS

        # A cached token the widget will reject; its JWT is still valid locally
        client._tokens[widgetid] = AulaToken(
            bearer_token="Bearer cached",
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=10),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )

        # Dates within a single week → one loop iteration
        from_dt = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
        to_dt = datetime(2026, 4, 3, 12, 0, tzinfo=timezone.utc)

        # Phase 1: widget rejects token → getAulaToken also fails → cascade.
        def phase1_response(url: str, **kwargs: Any) -> HttpResponse:
            if "aulaToken.getAulaToken" in url:
                return _make_response(500, text="Aula token endpoint down")
            return _make_response(401, text='{"message":"JWT-Token expired, please renew."}')

        with patch.object(client._session, "get", AsyncMock(side_effect=phase1_response)):
            with self.assertRaises(AulaApiError) as ctx:
                asyncio.run(client.get_weekly_plans([child], from_dt, to_dt))

        # The error must name the widget, the status and the failing endpoint
        err_msg = str(ctx.exception)
        self.assertIn("0004", err_msg, "widget id must be in the error")
        self.assertIn("500", err_msg, "HTTP status must be in the error")
        self.assertIn("aulaToken.getAulaToken", err_msg, "failing endpoint must be identified in the error")

        # The next poll can only recover from a clean cache
        self.assertNotIn(widgetid, client._tokens, "stale token must be evicted on force-refresh failure")

        # Phase 2: the next poll logs in first, which restores the login result phase 1 reset
        client._login_result = _meebook_login()
        client._is_logged_in = True

        fresh_jwt = _fresh_jwt()

        def phase2_response(url: str, **kwargs: Any) -> HttpResponse:
            if "aulaToken.getAulaToken" in url:
                return _make_response(200, {"data": fresh_jwt})
            return _make_response(200, [])

        with patch.object(client._session, "get", AsyncMock(side_effect=phase2_response)):
            plans = asyncio.run(client.get_weekly_plans([child], from_dt, to_dt))

        stored = client._tokens.get(widgetid)
        assert stored is not None
        self.assertEqual(stored.bearer_token, f"Bearer {fresh_jwt}")
        self.assertIsNotNone(stored.expires_at, "fresh token must have a decoded JWT exp")
        self.assertEqual(plans, [])


# ---------------------------------------------------------------------------
# _ensure_valid_token and _force_refresh_access_token
# ---------------------------------------------------------------------------

class TestEnsureValidToken(unittest.TestCase):
    """Tests for AulaClient._ensure_valid_token and _force_refresh_access_token."""

    def _make_client(self, expires_at: float = 0, refresh_token: str = "test-refresh") -> tuple[AulaClient, Mock]:
        login_client = Mock()
        login_client.tokens = {}
        login_client.renew_access_token = AsyncMock()
        self.token_update_callback = Mock()
        client = AulaClient(
            MagicMock(),
            access_token="test-access",
            refresh_token=refresh_token,
            expires_at=expires_at,
            mitid_username="test-user",
            login_client=login_client,
            token_update_callback=self.token_update_callback,
        )
        return client, login_client

    def test_token_still_valid_no_refresh(self):
        """Token not expired → no refresh call."""
        client, login_client = self._make_client(expires_at=time.time() + 600)
        asyncio.run(client._ensure_valid_token())
        login_client.renew_access_token.assert_not_called()

    def test_expired_token_successful_refresh(self):
        """Token expired → refresh succeeds → state updated."""
        client, login_client = self._make_client(expires_at=0)

        async def renew() -> bool:
            login_client.tokens.update({
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_at": time.time() + 3600,
            })
            return True
        login_client.renew_access_token.side_effect = renew

        asyncio.run(client._ensure_valid_token())

        self.assertEqual(client._access_token, "new-access")
        self.token_update_callback.assert_called_once_with("new-access", "new-refresh", ANY)

    def test_no_refresh_token_raises_credential_error(self):
        """No refresh token → MUST raise AulaCredentialError (legitimate reauth)."""
        client, _ = self._make_client(expires_at=0, refresh_token="")

        with self.assertRaises(AulaCredentialError):
            asyncio.run(client._ensure_valid_token())

    def test_token_expired_error_raises_credential_error(self):
        """TokenExpiredError from server → MUST raise AulaCredentialError."""
        client, login_client = self._make_client(expires_at=0)
        login_client.renew_access_token.side_effect = TokenExpiredError("expired")

        with self.assertRaises(AulaCredentialError):
            asyncio.run(client._ensure_valid_token())

    def test_network_error_raises_connection_error_not_credential(self):
        """NetworkError → ConnectionError, NOT AulaCredentialError (no reauth)."""
        client, login_client = self._make_client(expires_at=0)
        login_client.renew_access_token.side_effect = NetworkError("network down")

        with self.assertRaises(ConnectionError) as ctx:
            asyncio.run(client._ensure_valid_token())
        self.assertNotIsInstance(ctx.exception, AulaCredentialError)

    def test_renew_returns_false_raises_connection_error_not_credential(self):
        """renew_access_token() returns False → ConnectionError, NOT AulaCredentialError."""
        client, login_client = self._make_client(expires_at=0)
        login_client.renew_access_token.return_value = False

        with self.assertRaises(ConnectionError) as ctx:
            asyncio.run(client._ensure_valid_token())
        self.assertNotIsInstance(ctx.exception, AulaCredentialError)

    def test_force_refresh_success(self):
        """_force_refresh_access_token returns True on successful refresh."""
        client, login_client = self._make_client(expires_at=time.time() + 600)
        login_client.renew_access_token.return_value = True

        self.assertTrue(asyncio.run(client._force_refresh_access_token()))
        login_client.renew_access_token.assert_awaited_once()

    def test_force_refresh_transient_failure_returns_false(self):
        """_force_refresh_access_token returns False on transient failure (ConnectionError)."""
        client, login_client = self._make_client(expires_at=0)
        login_client.renew_access_token.return_value = False

        self.assertFalse(asyncio.run(client._force_refresh_access_token()))

    def test_force_refresh_credential_error_propagates(self):
        """_force_refresh_access_token lets AulaCredentialError propagate."""
        client, login_client = self._make_client(expires_at=0)
        login_client.renew_access_token.side_effect = TokenExpiredError("expired")

        with self.assertRaises(AulaCredentialError):
            asyncio.run(client._force_refresh_access_token())

    def test_force_refresh_unexpected_exception_returns_false(self):
        """_force_refresh_access_token catches unexpected (non-credential) exceptions."""
        client, login_client = self._make_client(expires_at=0)
        login_client.renew_access_token.side_effect = RuntimeError("unexpected")

        self.assertFalse(asyncio.run(client._force_refresh_access_token()))

    def test_concurrent_callers_refresh_once(self):
        """Two concurrent _ensure_valid_token calls → renew called exactly once."""
        client, login_client = self._make_client(expires_at=0)
        call_count = 0

        async def slow_renew() -> bool:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            login_client.tokens = {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_at": time.time() + 3600,
            }
            return True
        login_client.renew_access_token.side_effect = slow_renew

        async def ensure_twice() -> None:
            await asyncio.gather(client._ensure_valid_token(), client._ensure_valid_token())

        asyncio.run(ensure_twice())

        # The second caller waits on the lock, then sees the new expiry
        self.assertEqual(call_count, 1)


if __name__ == "__main__":
    unittest.main()
