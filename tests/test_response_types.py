"""Tests that the types the library declares for Aula's answers are the types Aula sends."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aula_connect.api.responses.get_daily_overview_response import AulaGetDailyOverviewResponse

from response_types import RESPONSE_TYPES, mismatches
from test_capture import _read_everything

CAPTURED = sorted((Path(__file__).parent / "api" / "fixtures").glob("diagnostics*.json"))
"""Diagnostics downloaded from a real account, kept on the machine they were captured on."""


def test_a_type_aula_does_not_send_and_a_key_it_leaves_out_are_found() -> None:
    answer: dict[str, Any] = {"status": {"code": 0, "message": "OK"}, "data": [{"id": "4526396", "status": 3}]}
    assert mismatches(AulaGetDailyOverviewResponse, answer) == [
        ".data[].id: declared int | NoneType, got str",
        ".version: missing",
    ]


def test_the_simulated_aula_answers_in_the_types_the_library_declares() -> None:
    _, _, client, _ = _read_everything()
    checked = {exchange.endpoint for exchange in client.api.recorder.exchanges() if exchange.endpoint in RESPONSE_TYPES}
    assert checked == set(RESPONSE_TYPES)
    for exchange in client.api.recorder.exchanges():
        if exchange.endpoint in RESPONSE_TYPES:
            assert mismatches(RESPONSE_TYPES[exchange.endpoint], exchange.response) == [], exchange.endpoint


@pytest.mark.skipif(not CAPTURED, reason="no diagnostics captured from a real account in tests/api/fixtures/")
@pytest.mark.parametrize("path", CAPTURED, ids=[path.name for path in CAPTURED])
def test_aula_answers_in_the_types_the_library_declares(path: Path) -> None:
    exchanges = json.loads(path.read_text())["data"]["aula"]["exchanges"]
    found = {
        exchange["endpoint"]: mismatches(RESPONSE_TYPES[exchange["endpoint"]], exchange["response"])
        for exchange in exchanges
        if exchange["endpoint"] in RESPONSE_TYPES and exchange["status"] == 200
    }
    assert {endpoint: places for endpoint, places in found.items() if places} == {}
