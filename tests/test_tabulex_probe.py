"""Tests of the read-only probe of Tabulex's login from Aula, against a simulated IST and Tabulex."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from bs4 import BeautifulSoup

from aula_connect import AulaClient, AulaLoginClient
from aula_connect.api.aula_errors import NoTabulexWidgetError
from aula_connect.api.models.aula_parser import now
from aula_connect.tabulex_probe import (
    MAX_HOPS,
    VERSION,
    ProbeAddress,
    ProbeCookie,
    ProbeForm,
    ProbePage,
    TabulexProbeReport,
    _auto_form,
    _page,
    allowed,
    follow,
    masked,
    masked_script,
)
from aula_connect.testing import SimulatedAulaApi, SimulatedTabulex

T = SimulatedTabulex
SP, IDP, PORTAL, ELSEWHERE = T.SP, T.IDP, T.PORTAL, T.ELSEWHERE

Arrange = Callable[[SimulatedAulaApi, SimulatedTabulex], None]


def _nothing(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
    return None


def _probe(arrange: Arrange = _nothing, own_session: bool = False, reads: Sequence[str] | Callable[[SimulatedTabulex], Sequence[str]] = ()) -> tuple[Any, SimulatedAulaApi, SimulatedTabulex, AulaClient]:
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
                    asked = reads(tabulex) if callable(reads) else reads
                    result = await client.probe_tabulex(chain, SimulatedTabulex.DOMAINS, tabulex.portal, asked)
            except NoTabulexWidgetError as error:
                result = error
            return result, aula, tabulex, client

    return asyncio.run(run())


def test_the_probe_follows_the_whole_login_as_a_browser_does_and_reads_the_portals_scripts() -> None:
    report, aula, tabulex, client = _probe()
    assert isinstance(report, TabulexProbeReport) and client.tabulex_probe is report and report.version == VERSION
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
    assert [(hop.method, hop.address.host, hop.address.path, hop.status, hop.next) for hop in report.hops] == [
        ("POST", SP, T.AULA_PHP, 302, "redirect"),
        ("GET", IDP, T.SSO, 302, "redirect"),
        ("GET", IDP, T.LOGIN, 200, "form"),
        ("POST", SP, T.ACS, 303, "redirect"),
        ("GET", PORTAL, "/", 302, "redirect"),
        ("GET", SP, T.PRP, 200, "form"),
        ("POST", PORTAL, "/", 302, "redirect"),
        ("GET", PORTAL, "/", 200, None),
    ]
    aula_php, sso, login, acs, _, prp, signin, page = report.hops
    assert aula_php.location == ProbeAddress(IDP, T.SSO, ("spentityid", "RelayState"))
    assert aula_php.cookies == (ProbeCookie("SimpleSAMLCitizenSessionID", "tabulex.test"),)
    assert sso.location == ProbeAddress(IDP, T.LOGIN, ("AuthState",)) and sso.address.query_names == ("spentityid", "RelayState")
    assert (login.form_action, login.form_fields, login.content_type) == (ProbeAddress(SP, T.ACS, ()), ("SAMLResponse", "RelayState"), "text/html")
    assert login.cookies == (ProbeCookie("SimpleSAMLCitizenAuthToken", "tabulex.test"),)
    assert login.page is not None and (login.page.title, login.page.scripts) == ("POST data", (ProbeAddress(IDP, "/simplesaml/resources/post.js", ()),))
    assert acs.location == ProbeAddress(PORTAL, "/", ())
    assert (prp.form_action, prp.form_fields) == (ProbeAddress(PORTAL, "/", ()), ("wa", "wresult", "wctx"))
    assert signin.cookies == (ProbeCookie("FedAuth", PORTAL),)
    assert page.page is not None and (page.page.title, page.page.inline) == ("Tabulex", ("var signedIn = true;",))
    assert (report.ended, report.stopped_at) == ("a page a browser stays on", None)
    [portal] = report.portal_hops
    assert (portal.method, portal.address, portal.status) == ("GET", ProbeAddress(PORTAL, "/", ()), 200)
    assert (report.portal_ended, report.portal_stopped_at) == ("a page a browser stays on", None)
    assert [(script.address.host, script.address.path, script.address.query_names, script.status, script.text) for script in report.scripts] == [
        (PORTAL, "/scripts/app.js", ("v",), 200, SimulatedTabulex.SCRIPT),
        (PORTAL, "/scripts/gone.js", (), 404, None),
        (PORTAL, "/closed.js", (), 0, None),
        ("cdn.elsewhere.test", "/lib.js", (), 0, None),
    ]
    assert report.cookies == (
        ProbeCookie("FedAuth", PORTAL),
        ProbeCookie("SimpleSAMLCitizenAuthToken", "tabulex.test"),
        ProbeCookie("SimpleSAMLCitizenSessionID", "tabulex.test"),
    )
    assert report.reads == ()
    assert not [request for request in tabulex.requests if "elsewhere" in request]


def test_the_reads_asked_are_read_with_get_once_logged_in_json_by_its_shape_and_pseudonymised() -> None:
    def reads(tabulex: SimulatedTabulex) -> list[str]:
        port = tabulex.portal.rsplit(":", 1)[1].rstrip("/")
        own = ["/api/children", "/api/broken", "/api/text", "/api/page", "/scripts/chunk.js", "/missing"]
        return [*own, "https://outside.example/x", f"ftp://{PORTAL}/x", f"http://{PORTAL}:1/x", f"http://{IDP}:{port}{T.SSO}"]

    report, _, tabulex, _ = _probe(reads=reads)
    children, broken, text, page, chunk, missing, outside, ftp, closed, sso = report.reads
    assert (children.asked, children.address, children.status, children.content_type) == ("/api/children", ProbeAddress(PORTAL, "/api/children", ()), 200, "application/json")
    assert children.shape == {
        ".": ["list"],
        "[]": ["object"],
        "[].absenceType": ["str"],
        "[].id": ["int"],
        "[].name": ["str"],
        "[].note": ["null"],
        "[].present": ["bool"],
    }
    [child] = children.answer
    assert (child["absenceType"], child["present"], child["note"]) == ("Sygdom", False, None)
    assert child["id"] != 7713 and "Alma" not in child["name"] and len(child["name"]) == len("Alma Hansen")
    assert (broken.status, broken.shape, broken.answer, broken.length) == (200, None, None, len("{not json"))
    assert (text.content_type, text.text, text.length) == ("text/plain", None, len("Alma er syg"))
    assert page.page is not None and (page.page.title, page.page.headings) == ("Fravær", ("Fravær «4»",))
    assert (chunk.content_type, chunk.text) == ("text/javascript", SimulatedTabulex.CHUNK)
    assert (missing.status, missing.shape, missing.page, missing.text) == (404, None, None, None)
    assert (outside.address, outside.status, outside.error) == (None, 0, "outside the domains followed")
    assert (ftp.address, ftp.error) == (None, "outside the domains followed")
    assert (closed.status, closed.error) == (0, "ClientConnectorError")
    assert (sso.status, sso.location) == (302, ProbeAddress(IDP, T.LOGIN, ("AuthState",)))
    assert [request for request in tabulex.requests if "/api/" in request and not request.startswith("GET ")] == []


def test_at_most_the_most_reads_are_read() -> None:
    report, _, _, _ = _probe(reads=tuple(f"/api/text?n={index}" for index in range(40)))
    assert len(report.reads) == 30


@pytest.mark.parametrize(("onward", "next_step"), [("refresh", "refresh"), ("script", "script")])
def test_a_meta_refresh_or_a_scripts_plain_redirect_is_followed(onward: str, next_step: str) -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        tabulex.onward = onward

    report, _, _, _ = _probe(arrange)
    acs = report.hops[3]
    assert (acs.address.path, acs.status, acs.next) == (T.ACS, 200, next_step)
    assert report.ended == "a page a browser stays on" and report.hops[-1].page is not None
    assert report.hops[-1].page.title == "Tabulex"


def test_a_temporary_redirect_keeps_the_method_and_the_form() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        tabulex.moved_acs = True

    report, _, tabulex, _ = _probe(arrange)
    assert [(hop.method, hop.address.path, hop.status) for hop in report.hops[3:5]] == [("POST", T.ACS, 307), ("POST", f"{T.ACS}2", 303)]
    assert report.ended == "a page a browser stays on" and f"POST {SP}{T.ACS}2" in tabulex.requests


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
    assert not [request for request in tabulex.requests if ELSEWHERE in request]
    assert [hop.address.path for hop in report.portal_hops] == ["/", T.PRP, T.DISCO]


def test_a_page_a_browser_stays_on_ends_the_chain_with_how_it_is_built_and_the_scripts_it_loads() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        tabulex.needs_javascript = True

    report, _, _, _ = _probe(arrange)
    login = report.hops[-1]
    assert (login.address.path, login.next, report.ended) == (T.LOGIN, None, "a page a browser stays on")
    assert login.page is not None and login.page.scripts == (ProbeAddress(IDP, "/login.js", ()),)
    disco = report.portal_hops[-1]
    assert disco.page is not None and disco.page.title == "Vælg institution (identitetsudbyder)"
    assert disco.page.forms[0].fields == (("return", "hidden"), ("idpentityid", "hidden"))
    assert report.portal_ended == "a page a browser stays on"
    assert [(script.address.host, script.address.path, script.status) for script in report.scripts] == [(IDP, "/login.js", 500), (SP, "/jquery.js", 403)]


def test_a_chain_longer_than_the_most_steps_is_given_up() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        tabulex.loops = True

    report, _, _, _ = _probe(arrange)
    assert (len(report.hops), report.ended) == (MAX_HOPS, f"{MAX_HOPS} steps")


def test_an_answer_that_leads_nowhere_ends_the_chain_with_how_its_page_is_built() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        aula.widget_fields["0047"] = {**tabulex.widget, "url": tabulex.widget_url.replace("made-up-app", "another-app")}

    report, _, tabulex, _ = _probe(arrange)
    [hop] = report.hops
    assert (hop.status, hop.next, report.ended) == (400, None, "an answer of HTTP 400")
    assert hop.page == ProbePage()
    assert tabulex.forms == []


def test_a_network_error_ends_the_chain_and_the_read_of_the_portal_with_its_kind() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        aula.widget_fields["0047"] = {**tabulex.widget, "url": f"http://{SP}:1{T.AULA_PHP}?appid=made-up-app"}

    async def unreachable_portal() -> TabulexProbeReport:
        async with SimulatedAulaApi() as aula, SimulatedTabulex(aula) as tabulex, tabulex.session() as chain:
            return await follow(chain, "0047", f"http://{SP}:1{T.AULA_PHP}", {}, SimulatedTabulex.DOMAINS, f"http://{PORTAL}:1/")

    report, _, _, _ = _probe(arrange)
    [hop] = report.hops
    assert (hop.status, hop.error, report.ended) == (0, "ClientConnectorError", "an error")
    [portal] = asyncio.run(unreachable_portal()).portal_hops
    assert (portal.status, portal.error) == (0, "ClientConnectorError")


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
    assert (report.hops, report.stopped_at, report.portal_hops, report.portal_stopped_at, report.scripts, report.cookies) == (
        (), SP, (), "outside.test", (), ()
    )
    assert tabulex.requests == []


def test_the_report_and_the_log_tell_no_token_cookie_assertion_field_or_name(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    report, aula, tabulex, _ = _probe(reads=("/api/children", "/api/text"))
    text = json.dumps(report.as_dict(), ensure_ascii=False)
    told = [*aula.widget_tokens, tabulex.assertion, tabulex.state, tabulex.sp_session, tabulex.login_token, tabulex.signed_in, tabulex.portal_session]
    told += ["made-up-app", "guardian-4821", "child-7713", "Alma", "7713"]
    assert [secret for secret in told if secret in text or secret in caplog.text] == []
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


_HIDDEN = '<form method="post" action="/acs"><input type="hidden" name="SAMLResponse" value="x"/></form>'


@pytest.mark.parametrize(
    ("page", "submits"),
    [
        (f'<script src="/simplesaml/resources/post.js"></script><noscript><p>Press</p></noscript>{_HIDDEN}', True),
        (_HIDDEN.replace("</form>", '<input type="submit" id="postLoginSubmitButton"/></form>'), True),
        (f"{_HIDDEN}<script>window.setTimeout('document.forms[0].submit()', 0);</script>", True),
        (f'<body onload="document.forms[0].submit()">{_HIDDEN}</body>', True),
        (f"{_HIDDEN}<script>function choose() {{ document.forms[0].submit(); }}</script>", False),
        (f'{_HIDDEN}<script src="/jquery.js"></script><button onclick="document.forms[0].submit()">Vælg</button>', False),
        (_HIDDEN, False),
        ('<form><input type="text" name="user"/></form><script>document.forms[0].submit()</script>', False),
        ('<form><input type="hidden" name="a"/><select name="b"></select></form><script>document.forms[0].submit()</script>', False),
        ("<form></form><script>document.forms[0].submit()</script>", False),
    ],
    ids=["simplesamlphp", "simplesamlphp button", "ad fs", "onload", "in a function", "on a button", "no script", "a field to fill", "a choice", "no fields"],
)
def test_only_a_form_of_hidden_fields_a_page_submits_as_it_loads_is_submitted(page: str, submits: bool) -> None:
    assert (_auto_form(BeautifulSoup(page, "html.parser")) is not None) is submits


def test_a_page_is_told_by_its_forms_scripts_masked_code_and_refresh_never_its_values_or_text() -> None:
    page = BeautifulSoup(
        "<title>Log ind 1234567 a1b2c3d4e5f6a1b2c3d4e5f6a1b2</title><h2>Der skete en  fejl</h2><h3>Sporings-ID: 8b506243b6</h3><h4> </h4>"
        '<meta http-equiv="refresh" content="0; url=\'/next?AuthState=secret-state\'">'
        '<form action="/simplesaml/login.php?AuthState=secret-state" method="post"><input type="hidden" name="AuthState" value="secret-state"/>'
        '<input name="user"/><select name="child"><option>Alma</option></select><button type="submit">Videre</button></form>'
        '<script src="/js/login.js?v=1"></script>'
        '<script>var token = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2"; window.location = "https://foraeldre.tabulex.net/?x=secret#/fravaer";</script>'
        "<p>Velkommen Alma</p>",
        "html.parser",
    )
    told = _page(page, "https://borger-aula-login.tabulex.dk/simplesaml/module.php/tabulexaulalogin/login.php?AuthState=secret-state")
    host = "borger-aula-login.tabulex.dk"
    assert told == ProbePage(
        "Log ind «7» «28»",
        ("Der skete en fejl", "Sporings-ID: 8b«6»b6"),
        (
            ProbeForm(
                ProbeAddress(host, "/simplesaml/login.php", ("AuthState",)),
                "POST",
                (("AuthState", "hidden"), ("user", "input"), ("child", "select"), ("", "submit")),
            ),
        ),
        (ProbeAddress(host, "/js/login.js", ("v",)),),
        ('var token = "«28»"; window.location = "foraeldre.tabulex.net/?x";',),
        ProbeAddress(host, "/next", ("AuthState",)),
        ProbeAddress("foraeldre.tabulex.net", "/", ("x",)),
    )
    assert "secret" not in repr(told) and "Alma" not in repr(told)


def test_a_scripts_text_is_kept_but_for_runs_long_enough_to_be_a_token() -> None:
    token = "a1" * 30
    assert masked_script(f'var api = "/api/fravaer"; var t = "{token}";') == 'var api = "/api/fravaer"; var t = "«60»";'


def test_a_page_without_forms_scripts_or_refresh_is_told_empty() -> None:
    assert _page(BeautifulSoup("<p>Hej</p><script> </script>", "html.parser"), "https://x.tabulex.dk/") == ProbePage()


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("f('/api/fravaer?child=7713')", "f('/api/fravaer?child')"),
        ("f(`${a}`)", "f(`«4»`)"),
        ('x = "say \\"hi\\""', 'x = "«10»"'),
        ("id = abcdefghijklmnopqrstuvwxyz0123", "id = «30»"),
        ("http('https://api.ist.dk/v1/sick')", "http('api.ist.dk/v1/sick')"),
    ],
)
def test_code_is_masked_but_for_its_addresses_hosts_and_paths(code: str, expected: str) -> None:
    assert masked(code) == expected
