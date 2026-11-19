"""Tests of the read-only probe of Tabulex's login from Aula, against a simulated IST and Tabulex."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from bs4 import BeautifulSoup

from aula_connect import AulaClient, AulaLoginClient
from aula_connect.api.aula_errors import NoTabulexWidgetError
from aula_connect.api.models.aula_parser import now
from aula_connect.tabulex_probe import MAX_HOPS, ProbeAddress, ProbeCookie, TabulexProbeReport, _auto_form, allowed, follow
from aula_connect.testing import SimulatedAulaApi, SimulatedTabulex

IDP, PORTAL, ELSEWHERE = SimulatedTabulex.IDP, SimulatedTabulex.PORTAL, SimulatedTabulex.ELSEWHERE
PRP = "/simplesaml/module.php/adfs/idp/prp.php"
AULA_PHP = "/simplesaml/module.php/tabulexaulalogin/aula.php"

Arrange = Callable[[SimulatedAulaApi, SimulatedTabulex], None]


def _nothing(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
    return None


def _probe(arrange: Arrange = _nothing, own_session: bool = False) -> tuple[Any, SimulatedAulaApi, SimulatedTabulex, AulaClient]:
    async def run() -> tuple[Any, SimulatedAulaApi, SimulatedTabulex, AulaClient]:
        async with (
            SimulatedAulaApi() as aula,
            SimulatedTabulex(aula) as tabulex,
            aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session,
            tabulex.session() as chain,
        ):
            aula.guardian["userId"] = "guardian-4821"
            aula.child["userId"] = "child-7713"
            aula.widgets.append("0047")
            aula.widget_fields["0047"] = tabulex.widget
            arrange(aula, tabulex)
            client = AulaClient(
                session,
                access_token=aula.access_token,
                refresh_token="refresh",
                expires_at=time.time() + 3600,
                mitid_username="parent",
                login_client=AulaLoginClient(session, "parent"),
            )
            aula.point(client.api)
            await client.login()
            try:
                if own_session:
                    result: Any = await client.probe_tabulex(None, ("nowhere.test",), "http://outside.test/")
                else:
                    result = await client.probe_tabulex(chain, SimulatedTabulex.DOMAINS, tabulex.portal)
            except NoTabulexWidgetError as error:
                result = error
            return result, aula, tabulex, client

    return asyncio.run(run())


def test_the_probe_follows_the_chain_posts_the_portals_form_and_reads_the_portal_and_its_own_scripts() -> None:
    report, aula, tabulex, client = _probe()
    assert isinstance(report, TabulexProbeReport) and client.tabulex_probe is report
    week = now().isocalendar()
    [form] = tabulex.forms
    assert form["aulaToken"] in aula.widget_tokens
    assert {name: value for name, value in form.items() if name != "aulaToken"} == {
        "sessionUUID": "guardian-4821",
        "isMobileApp": "false",
        "assuranceLevel": "2",
        "userProfile": "guardian",
        "childFilter": "child-7713",
        "institutionFilter": "S1",
        "group": "",
        "currentWeekNumber": f"{week.year}-W{week.week}",
    }
    assert report.widget_id == "0047"
    [login, idp, post, page] = report.hops
    assert (login.method, login.address, login.status) == ("POST", ProbeAddress(IDP, AULA_PHP, ("appid",)), 302)
    assert login.location == ProbeAddress(IDP, PRP, ("wa", "wtrealm", "wctx"))
    assert login.cookies == (ProbeCookie("SimpleSAMLCitizenSessionID", "tabulex.test"),)
    assert (idp.method, idp.status, idp.form_action, idp.form_fields) == ("GET", 200, ProbeAddress(PORTAL, "/", ()), ("wa", "wresult", "wctx"))
    assert not idp.needs_javascript
    assert (post.method, post.status, post.location, post.cookies) == ("POST", 302, ProbeAddress(PORTAL, "/", ()), (ProbeCookie("FedAuth", PORTAL),))
    assert (page.method, page.status, page.needs_javascript) == ("GET", 200, True)
    assert (report.ended, report.stopped_at) == ("a page that needs JavaScript", None)
    assert report.portal is not None and (report.portal.status, report.portal.needs_javascript) == (200, True)
    assert [(script.address.host, script.address.path, script.address.query_names, script.status, script.text) for script in report.scripts] == [
        (PORTAL, "/scripts/app.js", ("v",), 200, SimulatedTabulex.SCRIPT),
        (PORTAL, "/scripts/gone.js", (), 404, None),
        (PORTAL, "/closed.js", (), 0, None),
        ("cdn.elsewhere.test", "/lib.js", (), 0, None),
    ]
    assert not [request for request in tabulex.requests if "elsewhere" in request]


def test_a_stepped_up_login_asks_for_the_higher_assurance_level() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        aula.stepped_up = True

    _, _, tabulex, _ = _probe(arrange)
    assert tabulex.forms[0]["assuranceLevel"] == "3"


def test_a_host_outside_ists_and_tabulexs_stops_the_chain_unasked() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        tabulex.leave_to_elsewhere = True

    report, _, tabulex, _ = _probe(arrange)
    assert (report.ended, report.stopped_at) == ("a host outside the domains followed", ELSEWHERE)
    assert report.hops[-1].location == ProbeAddress(ELSEWHERE, "/login", ("SAMLRequest",))
    assert not [request for request in tabulex.requests if request.startswith(ELSEWHERE)]
    assert report.portal is not None and report.portal.status == 302 and report.portal.location is not None
    assert (report.portal.location.host, report.scripts) == (IDP, ())


def test_a_page_that_needs_javascript_ends_the_chain_and_is_reported() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        tabulex.needs_javascript = True

    report, _, tabulex, _ = _probe(arrange)
    assert report.hops[-1].address.path == PRP and report.hops[-1].needs_javascript
    assert report.ended == "a page that needs JavaScript"
    assert f"{IDP}/login.js" not in tabulex.requests


def test_a_chain_longer_than_the_most_steps_is_given_up() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        tabulex.loops = True

    report, _, _, _ = _probe(arrange)
    assert (len(report.hops), report.ended) == (MAX_HOPS, f"{MAX_HOPS} steps")


def test_an_answer_that_leads_nowhere_ends_the_chain() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        aula.widget_fields["0047"] = {**tabulex.widget, "url": tabulex.widget_url.replace("made-up-app", "another-app")}

    report, _, tabulex, _ = _probe(arrange)
    [hop] = report.hops
    assert (hop.status, hop.needs_javascript, report.ended) == (400, False, "an answer of HTTP 400 that leads nowhere")
    assert tabulex.forms == []


def test_a_network_error_ends_the_chain_and_the_read_of_the_portal_with_its_kind() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        aula.widget_fields["0047"] = {**tabulex.widget, "url": f"http://{IDP}:1{AULA_PHP}?appid=made-up-app"}

    async def unreachable_portal() -> TabulexProbeReport:
        async with SimulatedAulaApi() as aula, SimulatedTabulex(aula) as tabulex, tabulex.session() as chain:
            return await follow(chain, "0047", f"http://{IDP}:1{AULA_PHP}", {}, SimulatedTabulex.DOMAINS, f"http://{PORTAL}:1/")

    report, _, _, _ = _probe(arrange)
    [hop] = report.hops
    assert (hop.status, hop.error, report.ended) == (0, "ClientConnectorError", "an error")
    portal = asyncio.run(unreachable_portal()).portal
    assert portal is not None and (portal.status, portal.error) == (0, "ClientConnectorError")


@pytest.mark.parametrize("widget", [None, {"type": "normal"}], ids=["no widget", "not a sign-in"])
def test_a_login_without_ists_tabulex_sign_in_widget_is_refused(widget: dict[str, object] | None) -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        if widget is None:
            aula.widgets.remove("0047")
        else:
            aula.widget_fields["0047"] = {**tabulex.widget, **widget}

    error, _, tabulex, _ = _probe(arrange)
    assert isinstance(error, NoTabulexWidgetError) and tabulex.requests == []


def test_a_user_context_aula_tells_nothing_of_is_refused() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        async def no_content(request: web.Request) -> web.Response:
            return web.Response(status=204)

        aula.answers["profiles.getProfileContext"] = no_content

    error, _, _, _ = _probe(arrange)
    assert isinstance(error, NoTabulexWidgetError) and "nothing" in str(error)


def test_without_a_session_the_probe_has_its_own_and_never_leaves_the_domains_followed() -> None:
    report, _, tabulex, _ = _probe(own_session=True)
    assert (report.hops, report.stopped_at, report.portal, report.scripts) == ((), IDP, None, ())
    assert tabulex.requests == []


def test_the_report_and_the_log_tell_no_token_cookie_assertion_field_or_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    report, aula, tabulex, _ = _probe()
    text = json.dumps(report.as_dict(), ensure_ascii=False)
    secrets = [*aula.widget_tokens, tabulex.assertion, tabulex.idp_session, tabulex.portal_session, "made-up-app", "guardian-4821", "child-7713", "Fravær", "Alma"]
    assert [secret for secret in secrets if secret in text or secret in caplog.text] == []
    assert SimulatedTabulex.SCRIPT in [script["text"] for script in json.loads(text)["scripts"]]


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("saml.borger.ist.dk", True),
        ("ist.dk", True),
        ("foraeldre.tabulex.net.", True),
        ("SAML.Borger.Tabulex.DK", True),
        ("evilist.dk", False),
        ("tabulex.dk.example.com", False),
        ("", False),
    ],
)
def test_only_ists_and_tabulexs_hosts_are_followed(host: str, expected: bool) -> None:
    assert allowed(host, ("ist.dk", "tabulex.dk", "tabulex.net")) is expected


def test_a_page_that_submits_a_form_with_a_field_to_fill_is_no_form_it_submits_by_itself() -> None:
    page = BeautifulSoup('<form><input type="text" name="user"/></form><script>document.forms[0].submit()</script>', "html.parser")
    assert _auto_form(page) is None
