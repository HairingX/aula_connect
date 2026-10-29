"""Aula read with tokens that are kept fresh: the API client and the login client together."""

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
        self._proxy = AulaProxyClient(session, access_token, username_for_meebook=mitid_username)
        self._proxy.set_token_refresh_callback(self._force_refresh_access_token)

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
        """The birthdays at the children's institutions in the period."""
        await self._ensure_valid_token()
        return await self._proxy.get_birthday_events(profiles, start_datetime, end_datetime)

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
