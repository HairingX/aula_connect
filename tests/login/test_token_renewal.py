"""Tests of renewing the access token with the refresh token."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests

from aula_connect.api.aula_errors import AulaCredentialError
from aula_connect.client import AulaClient
from aula_connect.login import AulaLoginClient
from aula_connect.login.exceptions import NetworkError, TokenExpiredError


def _answering(status: int, body: object) -> AulaLoginClient:
    """A login client whose token endpoint answers `status` with the JSON `body`."""
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    client = AulaLoginClient(mitid_username="parent")
    setattr(client.session, "post", MagicMock(return_value=response))
    client.tokens = {"access_token": "old", "refresh_token": "refresh"}
    return client


def test_a_refresh_token_the_server_calls_invalid_grant_needs_a_new_login() -> None:
    """OAuth 2.0 answers 400 invalid_grant for an invalid, expired or revoked refresh token."""
    client = _answering(400, {"error": "invalid_grant", "error_description": "The refresh token is invalid."})
    with pytest.raises(TokenExpiredError):
        client.renew_access_token()


def test_another_bad_request_is_no_reason_to_log_in_again() -> None:
    assert _answering(400, {"error": "invalid_request"}).renew_access_token() is False
    assert _answering(400, "not an object").renew_access_token() is False


def test_a_server_error_is_transient() -> None:
    with pytest.raises(NetworkError):
        _answering(503, {}).renew_access_token()


def test_the_client_asks_for_a_new_login_when_the_refresh_token_is_no_longer_valid() -> None:
    login_client = _answering(400, {"error": "invalid_grant"})
    client = AulaClient("old", "refresh", 0.0, "parent", login_client)
    with pytest.raises(AulaCredentialError):
        client.connection_check()
