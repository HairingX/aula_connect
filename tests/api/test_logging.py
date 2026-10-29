"""Tests that the client logs neither secrets nor what Aula holds about the children."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock, patch

import pytest
from requests import Response

from aula_connect.api.aula_errors import AulaApiError
from aula_connect.api.aula_proxy_client import AulaProxyClient
from aula_connect.api.models.constants import AulaWidgetId
from aula_connect.api.models.module import (
    AulaChildProfile,
    AulaInstitutionGroup,
    AulaInstitutionProfile,
    AulaMessageThread,
    AulaProfile,
)
from aula_connect.redact import redact

SECRETS = ("s3cr3t-t0ken", "COOKIE-VALUE", "Alma Example", "Sensitive subject")
SCHOOL = AulaInstitutionProfile(id=11, institution_code="S1", institution_name="School")
CHILD = AulaChildProfile(
    first_name="Alma Example",
    id=11,
    institution_code="S1",
    institution_profile=SCHOOL,
    main_group=AulaInstitutionGroup(1, "3A", "3A"),
    name="Alma Example",
    profile_id=101,
    short_name="AE",
    user_id="alma",
)
PARENT = AulaProfile([CHILD], "Pat", [SCHOOL], "Pat Example", 201, "pat")


def _failed(status: int = 500) -> Mock:
    """A failed answer whose body, request headers and URL hold secrets and a child's name."""
    response = Mock(spec=Response)
    response.status_code = status
    response.ok = False
    response.reason = "Internal Server Error"
    response.text = json.dumps({"data": {"name": "Alma Example"}, "access_token": "s3cr3t-t0ken"})
    response.json = Mock(return_value={"status": {"message": "failed"}})
    response.request = Mock(
        url="https://www.aula.dk/api/v23?method=x&access_token=s3cr3t-t0ken",
        headers={"Cookie": "COOKIE-VALUE"},
        body="refresh_token=s3cr3t-t0ken",
    )
    return response


def _thread() -> Any:
    thread = Mock(spec=AulaMessageThread)
    thread.id = 1
    thread.subject = "Sensitive subject"
    thread.sensitive = False
    return thread


start = datetime(2026, 12, 28, tzinfo=timezone.utc)
end = datetime(2027, 1, 11, tzinfo=timezone.utc)
READS: dict[str, Callable[[AulaProxyClient], object]] = {
    "birthday events": lambda client: client.get_birthday_events([CHILD], start, end),
    "calendar events": lambda client: client.get_calendar_events([SCHOOL], start, end),
    "daily overviews": lambda client: client.get_daily_overviews([PARENT]),
    "message threads": lambda client: client.get_message_threads(),
    "messages": lambda client: client.get_messages(_thread()),
    "notifications": lambda client: client.get_notifications([CHILD]),
}


@pytest.mark.parametrize("read", READS.values(), ids=READS.keys())
def test_a_read_aula_refuses_logs_no_secret_and_no_childs_data(
    caplog: pytest.LogCaptureFixture, read: Callable[[AulaProxyClient], object]
) -> None:
    client = AulaProxyClient("s3cr3t-t0ken")
    caplog.set_level(logging.DEBUG)
    with (
        patch.object(client._session, "get", return_value=_failed()),
        patch.object(client._session, "post", return_value=_failed()),
        pytest.raises(AulaApiError),
    ):
        read(client)
    assert "HTTP 500" in caplog.text
    for secret in SECRETS:
        assert secret not in caplog.text


def test_a_widget_token_aula_refuses_logs_no_body(caplog: pytest.LogCaptureFixture) -> None:
    client = AulaProxyClient("s3cr3t-t0ken")
    caplog.set_level(logging.DEBUG)
    with patch.object(client._session, "get", return_value=_failed()):
        client._refresh_token(AulaWidgetId.WEEKPLAN_PARENTS)
    assert "Failed to refresh token for widget 0004: HTTP 500" in caplog.text
    for secret in SECRETS:
        assert secret not in caplog.text


def test_a_widget_token_that_is_no_text_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    client = AulaProxyClient("s3cr3t-t0ken")
    response = Mock(spec=Response)
    response.status_code = 200
    response.ok = True
    response.json = Mock(return_value={"data": {"token": "s3cr3t-t0ken"}})
    with patch.object(client._session, "get", return_value=response):
        client._refresh_token(AulaWidgetId.WEEKPLAN_PARENTS)
    assert "non-string data (dict)" in caplog.text
    assert "s3cr3t-t0ken" not in caplog.text


@pytest.mark.parametrize(
    "text",
    [
        "HTTPSConnectionPool(host='www.aula.dk'): Max retries exceeded with url: /api/v23?method=x&access_token=s3cr3t-t0ken",
        "https://www.aula.dk/auth/login.php?type=unilogin&code=s3cr3t-t0ken&state=1",
        '{"refresh_token": "s3cr3t-t0ken"}',
        "password=s3cr3t-t0ken",
    ],
)
def test_redact_takes_out_tokens_codes_and_passwords(text: str) -> None:
    assert "s3cr3t-t0ken" not in redact(text)
    assert "REDACTED" in redact(text)


def test_the_login_clients_log_takes_out_the_authorization_code(caplog: pytest.LogCaptureFixture) -> None:
    from aula_connect.login.client import AulaLoginClient

    client = AulaLoginClient(mitid_username="parent")
    client.log("Found OAuth callback URL: https://www.aula.dk/?code=s3cr3t-t0ken", "ERROR")
    assert "code=REDACTED" in caplog.text
    assert "s3cr3t-t0ken" not in caplog.text
