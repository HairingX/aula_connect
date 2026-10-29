from typing import Callable, List
import datetime
import logging
import asyncio
import time

import aiohttp

from .api.const import API_VERSION
from .api.models.constants import AulaWidgetId
from .api.module import (
    AulaBirthdayEvent,
    AulaCalendarEvent,
    AulaDailyOverview,
    AulaEasyiqWeeklyPlan,
    AulaInstitutionProfile,
    AulaLoginData,
    AulaMessageThread,
    AulaProfile,
    AulaProxyClient,
    AulaWeeklyNewsletter,
    AulaWeeklyPlan,
    AulaChildProfile,
    AULA_NOTIFICATION_TYPES,
)
from .api.aula_errors import AulaCredentialError
from .login import AulaLoginClient
from .redact import redact
from .login.exceptions import NetworkError, TokenExpiredError

_LOGGER = logging.getLogger(__name__)

TOKEN_REFRESH_BUFFER_SECONDS = 300
"""Refresh tokens 5 minutes before expiry."""


class AulaClient:
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
        self._access_token: str = access_token
        self._refresh_token: str = refresh_token
        self._expires_at: float = expires_at
        self._mitid_username = mitid_username
        self._login_client = login_client
        self._token_update_callback = token_update_callback
        self._token_lock = asyncio.Lock()
        self._proxy = AulaProxyClient(session, access_token, username_for_meebook=mitid_username)
        self._proxy.set_token_refresh_callback(self._force_refresh_access_token)

    async def connection_check(self) -> None:
        """
        Attempts to log in using the proxy with token-based auth.
        Raises:
            AulaCredentialError: If access to the Aula API is denied.
            ConnectionRefusedError: If the API URL is unreachable.
        """
        await self._ensure_valid_token()
        await self._proxy.login()
        self.aula_version = self._proxy.api_version

    def has_widget(self, widgetid: AulaWidgetId):
        return self._proxy.has_widget(widgetid)

    async def login(self) -> AulaLoginData:
        await self._ensure_valid_token()
        return await self._proxy.login()

    async def _force_refresh_access_token(self) -> bool:
        """Force-refresh the access token, bypassing the expiry check.

        Used as a callback by AulaProxyClient when it receives a 401 from the
        Aula API after the token was already validated — i.e. a transient
        server-side issue.  Returns True on success, False on transient failure.

        Raises:
            AulaCredentialError: If credentials are permanently invalid
                (expired refresh token, no refresh token). This must propagate
                to the coordinator so reauth is triggered immediately.
        """
        self._expires_at = 0  # Force the expiry check to trigger a refresh
        try:
            await self._ensure_valid_token()
            return True
        except AulaCredentialError:
            raise  # Permanent credential failure — must trigger reauth
        except Exception:
            _LOGGER.debug("Forced token refresh failed (transient)", exc_info=True)
            return False

    async def _ensure_valid_token(self) -> None:
        """Check token expiration and refresh if needed, once for callers that ask at the same time."""
        if time.time() < self._expires_at - TOKEN_REFRESH_BUFFER_SECONDS:
            return  # Token still valid

        async with self._token_lock:
            # Double-check after acquiring lock — another caller may have refreshed
            if time.time() < self._expires_at - TOKEN_REFRESH_BUFFER_SECONDS:
                return

            # Guard: no refresh token means we genuinely need re-authentication
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
                # Refresh token permanently invalid — trigger reauth
                raise AulaCredentialError(
                    "Refresh token expired, re-authentication required"
                ) from err
            except (NetworkError, OSError) as err:
                # Transient network failure — don't trigger reauth, let coordinator retry
                _LOGGER.warning("Network error during token refresh: %s", redact(err))
                raise ConnectionError(f"Network error during token refresh: {redact(err)}") from None

            if not success:
                # renew_access_token() returns False for transient issues (malformed
                # server response, unexpected HTTP status, generic exceptions) — these
                # are NOT credential rejections and must NOT trigger MitID reauth.
                _LOGGER.warning("Token refresh returned False — treating as transient failure")
                raise ConnectionError("Token refresh failed — server returned an unexpected response")

            # Extract all new values before updating state
            tokens = self._login_client.tokens or {}
            new_access = str(tokens["access_token"])
            new_refresh = str(tokens.get("refresh_token", self._refresh_token))
            new_expires = float(tokens.get("expires_at", time.time() + 3600))

            # Update in-memory state
            self._access_token = new_access
            self._refresh_token = new_refresh
            self._expires_at = new_expires
            self._proxy.update_token(new_access)

            _LOGGER.debug("Token refreshed successfully, expires at %s", new_expires)

            # Persist tokens
            if self._token_update_callback:
                self._token_update_callback(new_access, new_refresh, new_expires)

    async def get_birthday_events(
        self,
        profiles: List[AulaChildProfile],
        start_datetime: datetime.datetime,
        end_datetime: datetime.datetime,
    ) -> List[AulaBirthdayEvent]:
        await self._ensure_valid_token()
        return await self._proxy.get_birthday_events(profiles, start_datetime, end_datetime)

    async def get_daily_overviews(
        self, profiles: List[AulaProfile]
    ) -> List[AulaDailyOverview]:
        await self._ensure_valid_token()
        return await self._proxy.get_daily_overviews(profiles)

    async def get_calendar_events(
        self,
        profiles: List[AulaInstitutionProfile],
        start_datetime: datetime.datetime,
        end_datetime: datetime.datetime,
    ) -> List[AulaCalendarEvent]:
        await self._ensure_valid_token()
        return await self._proxy.get_calendar_events(profiles, start_datetime, end_datetime)

    async def get_message_threads(self) -> List[AulaMessageThread]:
        await self._ensure_valid_token()
        return await self._proxy.get_message_threads()

    async def get_notifications(
        self, profiles: List[AulaChildProfile]
    ) -> List[AULA_NOTIFICATION_TYPES]:
        await self._ensure_valid_token()
        return await self._proxy.get_notifications(profiles)

    async def get_weekly_plans(
        self,
        profiles: List[AulaChildProfile],
        start_datetime: datetime.datetime,
        end_datetime: datetime.datetime,
    ) -> List[AulaWeeklyPlan]:
        await self._ensure_valid_token()
        return await self._proxy.get_weekly_plans(profiles, start_datetime, end_datetime)

    async def get_easyiq_weekly_plans(
        self,
        profiles: List[AulaChildProfile],
        start_datetime: datetime.datetime,
        end_datetime: datetime.datetime,
    ) -> List[AulaEasyiqWeeklyPlan]:
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
        await self._ensure_valid_token()
        return await self._proxy.get_newsletters(profiles, start_datetime, end_datetime)
