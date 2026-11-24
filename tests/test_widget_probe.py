"""Tests of the read-only probe of the services Aula's widgets log in to, against a simulated IST and Tabulex."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Sequence

import aiohttp
import pytest
from aiohttp import web
from bs4 import BeautifulSoup

from aula_connect import AulaClient, AulaLoginClient
from aula_connect.api.models.aula_parser import now
from aula_connect.testing import SimulatedAulaApi, SimulatedTabulex
from aula_connect.widget_probe import (
    MAX_HOPS,
    VERSION,
    ProbeAddress,
    ProbeCookie,
    ProbeForm,
    ProbePage,
    WidgetProbe,
    WidgetProbeReport,
    _auto_form,
    _changes,
    _page,
    found_in,
    masked,
    masked_script,
    probe,
    under,
)

T = SimulatedTabulex
SP, IDP, PORTAL, ELSEWHERE, OTHER = T.SP, T.IDP, T.PORTAL, T.ELSEWHERE, T.OTHER
NOT_FOLLOWED = ("elsewhere.test",)

Arrange = Callable[[SimulatedAulaApi, SimulatedTabulex], None]


def _nothing(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
    return None


def _probe(
    arrange: Arrange = _nothing,
    own_session: bool = False,
    reads: Sequence[str] | Callable[[SimulatedTabulex], Sequence[str]] = (),
    quoting: bool = False,
) -> tuple[WidgetProbeReport, SimulatedAulaApi, SimulatedTabulex, AulaClient]:
    async def run() -> tuple[WidgetProbeReport, SimulatedAulaApi, SimulatedTabulex, AulaClient]:
        async with (
            SimulatedAulaApi() as aula,
            SimulatedTabulex(aula) as tabulex,
            aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session,
            aiohttp.ClientSession(connector=tabulex.connector()) if quoting else tabulex.session() as chain,
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
            asked = reads(tabulex) if callable(reads) else reads
            if own_session:
                report = await client.probe_widgets(None, asked, ("tabulex.test",))
            else:
                report = await client.probe_widgets(chain, asked, NOT_FOLLOWED)
            return report, aula, tabulex, client

    return asyncio.run(run())


def _tabulex(report: WidgetProbeReport) -> WidgetProbe:
    [widget] = [widget for widget in report.widgets if widget.widget_id == "0047"]
    return widget


def test_the_probe_follows_the_whole_login_as_a_browser_does_and_reads_the_portals_scripts() -> None:
    report, aula, tabulex, client = _probe()
    assert client.widget_probe is report and report.version == VERSION
    widget = _tabulex(report)
    assert (widget.supplier, widget.start) == ("IST", ProbeAddress(SP, T.AULA_PHP, ("appid",)))
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
    assert [(hop.method, hop.address.host, hop.address.path, hop.status, hop.next) for hop in widget.hops] == [
        ("POST", SP, T.AULA_PHP, 302, "redirect"),
        ("GET", IDP, T.SSO, 302, "redirect"),
        ("GET", IDP, T.LOGIN, 200, "form"),
        ("POST", SP, T.ACS, 303, "redirect"),
        ("GET", PORTAL, "/", 302, "redirect"),
        ("GET", SP, T.PRP, 200, "form"),
        ("POST", PORTAL, "/", 302, "redirect"),
        ("GET", PORTAL, "/", 200, None),
    ]
    aula_php, sso, login, acs, _, prp, signin, page = widget.hops
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
    assert (widget.ended, widget.stopped_at, widget.hosts) == ("a page a browser stays on", None, (SP, IDP, PORTAL))
    assert [(script.address.host, script.address.path, script.address.query_names, script.status, script.text) for script in widget.scripts] == [
        (PORTAL, "/scripts/app.js", ("v",), 200, SimulatedTabulex.SCRIPT),
        (PORTAL, "/scripts/gone.js", (), 404, None),
        (PORTAL, "/closed.js", (), 0, None),
        ("cdn.elsewhere.test", "/lib.js", (), 0, None),
        (T.CDN, "/lib.js", (), 200, tabulex.cdn_script),
    ]
    assert widget.cookies == (
        ProbeCookie("FedAuth", PORTAL),
        ProbeCookie("SimpleSAMLCitizenAuthToken", "tabulex.test"),
        ProbeCookie("SimpleSAMLCitizenSessionID", "tabulex.test"),
    )
    assert not [request for request in tabulex.requests if "elsewhere" in request]


def test_the_addresses_the_services_code_names_are_read_but_those_that_change_and_json_by_its_shape_pseudonymised() -> None:
    report, _, tabulex, _ = _probe()
    widget = _tabulex(report)
    api = tabulex.cdn_script.split('"')[1].removesuffix("/v1/token")
    assert widget.candidates == (
        "/api/children",
        "api/children/{childId}/absence",
        "/api/fravaer/meldSyg",
        "/Account/LogOff",
        "/api/settings?from",
        "views/fravaer.html",
        "scripts/chunk.js",
        "https://cdn.elsewhere.test/x/y",
        "api/{unknown}/x",
        f"{api}/v1/token",
        f"{api}/v1/children",
    )
    assert [(read.asked, read.found, read.status) for read in widget.reads] == [
        ("/api/children", "code", 200),
        ("/api/settings?from", "code", 200),
        (f"{api}/v1/token", "code", 200),
        (f"{api}/v1/children", "code", 200),
        ("views/fravaer.html", "code", 200),
        ("scripts/chunk.js", "code", 200),
        ("https://cdn.elsewhere.test/x/y", "code", 0),
        ("api/children/«childId»/absence", "filled", 200),
    ]
    children, settings, token, api_children, view, chunk, cdn, absence = widget.reads
    assert token.shape == {".": ["object"], "access_token": ["str"], "expires_in": ["int"]}
    assert token.answer["access_token"] == "x" * len(tabulex.api_token)
    assert api_children.address == ProbeAddress(T.API, "/v1/children", ()) and api_children.shape is not None
    assert children.shape == {
        ".": ["list"],
        "[]": ["object"],
        "[].absenceType": ["str"],
        "[].childId": ["int"],
        "[].name": ["str"],
        "[].note": ["null"],
        "[].present": ["bool"],
    }
    [child] = children.answer
    assert (child["absenceType"], child["present"], child["note"]) == ("Sygdom", False, None)
    assert child["childId"] != 7713 and "Alma" not in child["name"] and len(child["name"]) == len("Alma Hansen")
    assert settings.answer == {"sickReportsEnabled": True} and settings.address == ProbeAddress(PORTAL, "/api/settings", ("from",))
    assert view.page is not None and view.page.headings == ("Meld fravær",)
    assert view.page.forms == (ProbeForm(None, "GET", (("fra", "date"), ("aarsag", "select"))),)
    assert (chunk.content_type, chunk.text) == ("text/javascript", SimulatedTabulex.CHUNK)
    assert (cdn.address, cdn.error) == (None, "on no site the chain reached")
    assert absence.address == ProbeAddress(PORTAL, "/api/children/«childId»/absence", ())
    assert absence.shape == {".": ["list"], "[]": ["object"], "[].absenceType": ["str"], "[].date": ["str"]}
    asked = [request for request in tabulex.requests if request.split()[1].startswith(PORTAL)]
    assert not [request for request in asked if "meldSyg" in request or "LogOff" in request or "unknown" in request or "logo" in request]


def test_every_widget_that_logs_in_to_a_service_of_its_own_is_probed_each_with_its_own_cookies() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        aula.widgets.extend(["0100", "0101", "0102"])
        aula.widget_fields["0100"] = tabulex.other_widget
        aula.widget_fields["0101"] = {"type": "secure", "url": "/kisijal/D0119V0001"}
        aula.widget_fields["0102"] = {"type": "sso", "url": "/relative"}

    report, _, _, _ = _probe(arrange)
    assert [(widget.widget_id, widget.supplier) for widget in report.widgets] == [("0047", "IST"), ("0100", "Hjernen&Hjertet")]
    other = report.widgets[1]
    assert [(hop.method, hop.address.host, hop.status) for hop in other.hops] == [("POST", OTHER, 200)]
    assert other.hops[0].page is not None and other.hops[0].page.title == "Hjerne"
    assert (other.ended, other.cookies, other.hosts) == ("a page a browser stays on", (), (OTHER,))


def test_a_relative_address_is_read_against_the_pages_base_and_each_base_of_an_api_its_query_filled() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        aula.widgets.remove("0047")
        aula.widgets.append("0100")
        aula.widget_fields["0100"] = tabulex.other_widget

    [other] = _probe(arrange)[0].widgets
    [rest] = [found for found in other.candidates if found.endswith("/rest/")]
    assert other.candidates == (rest, "data/kids", "data/kid?kidId")
    assert [(read.asked, read.found, read.address and read.address.path, read.status) for read in other.reads] == [
        (rest, "code", "/rest/", 404),
        ("data/kids", "code", "/app/data/kids", 404),
        ("data/kids", "code", "/rest/data/kids", 200),
        ("data/kid?kidId", "code", "/app/data/kid", 404),
        ("data/kid?kidId", "code", "/rest/data/kid", 404),
        ("data/kid?kidId=«kidId»", "filled", "/app/data/kid", 404),
        ("data/kid?kidId=«kidId»", "filled", "/rest/data/kid", 200),
    ]
    assert other.reads[-1].shape == {".": ["object"], "kidId": ["int"], "name": ["str"]} and other.reads[-1].answer["kidId"] != 55


def test_once_a_widgets_time_runs_out_no_more_is_read_and_what_was_not_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aula_connect.widget_probe.MAX_SECONDS", -1)
    widget = _tabulex(_probe(reads=("/api/text",))[0])
    assert (widget.ended, widget.reads) == ("a page a browser stays on", ())
    assert widget.skipped == 7 + 1


def test_a_widget_whose_token_aula_refuses_is_left_out() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        async def refused(request: web.Request) -> web.Response:
            return web.Response(status=500)

        aula.answers["aulaToken.getAulaToken"] = refused

    report, _, tabulex, _ = _probe(arrange)
    assert (report.widgets, tabulex.requests) == ((), [])


def test_the_portals_base64_session_is_sent_back_as_it_was_set() -> None:
    report, _, _, _ = _probe()
    assert _tabulex(report).hops[-1].status == 200
    quoted, _, _, _ = _probe(quoting=True)
    broken = _tabulex(quoted).hops[-1]
    assert (broken.address.host, broken.status) == (PORTAL, 500)
    assert broken.page is not None and broken.page.title is not None and "Base-64" in broken.page.title
    assert _tabulex(quoted).reads == ()


def test_the_addresses_asked_are_read_with_get_once_logged_in() -> None:
    def reads(tabulex: SimulatedTabulex) -> list[str]:
        port = tabulex.portal.rsplit(":", 1)[1].rstrip("/")
        own = ["/api/broken", "/api/text", "/api/page", "/missing", "/api/fravaer/meldSyg"]
        return [*own, "https://outside.example/x", f"ftp://{PORTAL}/x", f"http://{PORTAL}:1/x", f"http://{IDP}:{port}{T.SSO}"]

    report, _, tabulex, _ = _probe(reads=reads)
    asked = [read for read in _tabulex(report).reads if read.found == "asked"]
    broken, text, page, missing, changes, outside, ftp, closed, sso = asked
    assert (broken.status, broken.shape, broken.answer, broken.length) == (200, None, None, len("{not json"))
    assert (text.content_type, text.text, text.length) == ("text/plain", None, len("Alma er syg"))
    assert page.page is not None and (page.page.title, page.page.headings) == ("Fravær", ("Fravær «4»",))
    assert (missing.status, missing.shape, missing.page, missing.text) == (404, None, None, None)
    assert changes.status == 404 and f"GET {PORTAL}/api/fravaer/meldSyg" in tabulex.requests
    assert (outside.address, outside.status, outside.error) == (None, 0, "on no site the chain reached")
    assert (ftp.address, ftp.error) == (None, "on no site the chain reached")
    assert (closed.status, closed.error) == (0, "ClientConnectorError")
    assert (sso.status, sso.location) == (302, ProbeAddress(IDP, T.LOGIN, ("AuthState",)))


def test_at_most_the_most_reads_are_read() -> None:
    widget = _tabulex(_probe(reads=tuple(f"/api/text?n={index}" for index in range(40)))[0])
    assert (len([read for read in widget.reads if read.found == "asked"]), widget.skipped) == (30, 10)


@pytest.mark.parametrize(("onward", "next_step"), [("refresh", "refresh"), ("script", "script")])
def test_a_meta_refresh_or_a_scripts_plain_redirect_is_followed(onward: str, next_step: str) -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        tabulex.onward = onward

    widget = _tabulex(_probe(arrange)[0])
    acs = widget.hops[3]
    assert (acs.address.path, acs.status, acs.next) == (T.ACS, 200, next_step)
    assert widget.ended == "a page a browser stays on" and widget.hops[-1].page is not None
    assert widget.hops[-1].page.title == "Tabulex"


def test_a_temporary_redirect_keeps_the_method_and_the_form() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        tabulex.moved_acs = True

    report, _, tabulex, _ = _probe(arrange)
    widget = _tabulex(report)
    assert [(hop.method, hop.address.path, hop.status) for hop in widget.hops[3:5]] == [("POST", T.ACS, 307), ("POST", f"{T.ACS}2", 303)]
    assert widget.ended == "a page a browser stays on" and f"POST {SP}{T.ACS}2" in tabulex.requests


def test_a_stepped_up_login_asks_for_the_higher_assurance_level() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        aula.stepped_up = True

    _, _, tabulex, _ = _probe(arrange)
    assert tabulex.forms[0]["assuranceLevel"] == "3"


def test_a_login_the_probe_does_not_follow_stops_the_chain_unasked() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        tabulex.leave_to_elsewhere = True

    report, _, tabulex, _ = _probe(arrange)
    widget = _tabulex(report)
    assert (widget.ended, widget.stopped_at) == ("a login the probe does not follow", ELSEWHERE)
    assert widget.hops[-1].location == ProbeAddress(ELSEWHERE, "/login", ("SAMLRequest",))
    assert not [request for request in tabulex.requests if ELSEWHERE in request]
    assert (widget.scripts, widget.candidates, widget.reads) == ((), (), ())


def test_a_page_a_browser_stays_on_ends_the_chain_with_how_it_is_built_and_the_scripts_it_loads() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        tabulex.needs_javascript = True

    widget = _tabulex(_probe(arrange)[0])
    login = widget.hops[-1]
    assert (login.address.path, login.next, widget.ended) == (T.LOGIN, None, "a page a browser stays on")
    assert login.page is not None and login.page.scripts == (ProbeAddress(IDP, "/login.js", ()),)
    assert [(script.address.host, script.address.path, script.status) for script in widget.scripts] == [(IDP, "/login.js", 500)]


def test_a_chain_longer_than_the_most_steps_is_given_up() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        tabulex.loops = True

    widget = _tabulex(_probe(arrange)[0])
    assert (len(widget.hops), widget.ended) == (MAX_HOPS, f"{MAX_HOPS} steps")


def test_an_answer_that_leads_nowhere_ends_the_chain_with_how_its_page_is_built() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        aula.widget_fields["0047"] = {**tabulex.widget, "url": tabulex.widget_url.replace("made-up-app", "another-app")}

    report, _, tabulex, _ = _probe(arrange)
    [hop] = _tabulex(report).hops
    assert (hop.status, hop.next, _tabulex(report).ended) == (400, None, "an answer of HTTP 400")
    assert hop.page == ProbePage()
    assert tabulex.forms == []


def test_a_network_error_ends_the_chain_with_its_kind() -> None:
    async def unreachable() -> WidgetProbe:
        async with SimulatedAulaApi() as aula, SimulatedTabulex(aula) as tabulex, tabulex.session() as chain:
            return await probe(chain, "0047", "IST", f"http://{SP}:1{T.AULA_PHP}", {}, (), NOT_FOLLOWED)

    widget = asyncio.run(unreachable())
    [hop] = widget.hops
    assert (hop.status, hop.error, widget.ended) == (0, "ClientConnectorError", "an error")


def test_a_user_context_aula_tells_nothing_of_has_no_widgets() -> None:
    def arrange(aula: SimulatedAulaApi, tabulex: SimulatedTabulex) -> None:
        async def no_content(request: web.Request) -> web.Response:
            return web.Response(status=204)

        aula.answers["profiles.getProfileContext"] = no_content

    report, _, tabulex, _ = _probe(arrange)
    assert (report.widgets, tabulex.requests) == ((), [])


def test_without_a_session_the_probe_has_its_own_and_never_goes_into_a_login_not_followed() -> None:
    report, _, tabulex, _ = _probe(own_session=True)
    widget = _tabulex(report)
    assert (widget.hops, widget.stopped_at, widget.hosts, widget.scripts, widget.cookies) == ((), SP, (), (), ())
    assert tabulex.requests == []


def test_the_report_and_the_log_tell_no_token_cookie_assertion_field_or_name(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    report, aula, tabulex, _ = _probe(reads=("/api/text",))
    text = json.dumps(report.as_dict(), ensure_ascii=False)
    told = [*aula.widget_tokens, tabulex.assertion, tabulex.state, tabulex.sp_session, tabulex.login_token, tabulex.signed_in, tabulex.portal_session]
    told += [tabulex.api_token, "made-up-app", "guardian-4821", "child-7713", "Alma", "7713"]
    assert [secret for secret in told if secret in text or secret in caplog.text] == []
    assert SimulatedTabulex.SCRIPT in [script["text"] for widget in json.loads(text)["widgets"] for script in widget["scripts"]]


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("login.aula.dk", True),
        ("aula.dk", True),
        ("MitID.dk.", True),
        ("evilaula.dk", False),
        ("aula.dk.example.com", False),
    ],
)
def test_a_host_is_under_a_domain_only_as_it_or_a_subdomain(host: str, expected: bool) -> None:
    assert under(host, ("aula.dk", "mitid.dk")) is expected


@pytest.mark.parametrize(
    ("address", "changes"),
    [
        ("/api/fravaer/meldSyg", True),
        ("/Account/LogOff", True),
        ("/account/logoff", True),
        ("api/children/delete", True),
        ("/api/saveAbsence", True),
        ("/api/absence/save?x=1", True),
        ("/api/SletFravaer", True),
        ("/api/settings", False),
        ("/api/address", False),
        ("/api/posts", False),
        ("/api/fravaer", False),
        ("/api/children?delete=1", False),
    ],
)
def test_an_address_that_names_a_change_is_told_by_a_word_of_its_path(address: str, changes: bool) -> None:
    assert _changes(address) is changes


def test_the_addresses_code_names_leave_out_media_types_assets_and_query_values() -> None:
    code = (
        'a("/api/x?child=7713&week=2"); b("text/html"); c("/img/a.png"); d("./"); e("dd/MM/yyyy");'
        ' f("https://host.test:8443/api/y"); g("/api/x?child=1"); h("not-an-address")'
    )
    assert found_in(code) == ["/api/x?child&week", "dd/MM/yyyy", "https://host.test:8443/api/y", "/api/x?child"]


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
