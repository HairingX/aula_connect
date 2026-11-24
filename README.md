# aula_connect

A Python client for [Aula](https://www.aula.dk), the Danish school and institution platform. It
logs in through MitID - with the MitID app's QR code or code - and reads the children's
profiles, daily overviews (presence), calendars, birthdays, messages, notifications, weekly
plans (Meebook, EasyIQ, MinUddannelse) and newsletters into typed models.

It is the library the Home Assistant integration
[ha_aula_connect](https://github.com/HairingX/ha_aula_connect) is built on.

It is asynchronous, and runs on the [aiohttp](https://docs.aiohttp.org) session the caller gives
it. A login's cookies are its own, so each login and each client has a session of its own, not one
shared with other services:

```python
import aiohttp
from aula_connect import AulaClient, AulaLoginClient

async with aiohttp.ClientSession() as session:
    login = AulaLoginClient(session, mitid_username="...")  # approve in the MitID app
    tokens = (await login.authenticate())["tokens"]
    client = AulaClient(
        session,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_at=tokens["expires_at"],
        mitid_username="...",
        login_client=login,
    )
    data = await client.login()
```

While the login runs, `login.get_qr_codes_svg()` gives the two QR codes to show in turn for the
MitID app to scan.

## What a guardian does in Aula

> **Warning: none of these writes has been sent to the real Aula yet.** They are built from what
> Aula's own web portal sends, and tested only against the simulated Aula. Until each has been
> tried once against a real account, treat it as untested.

Each write is sent once: never again after a failure of the network or of Aula's server, as Aula
may have done it, only once more where Aula refused the access token, once it is renewed. A write
is not kept with the answers (below), as it may hold what the user wrote. What Aula's portal would
not send is refused with `ValueError`, before anything is sent.

- **Presence module.** `get_presence_configurations(children)` tells, per child, what the
  guardian's dashboard may do with each part of Aula's presence module (Komme/gå), such as
  `report_sick` or `vacation`: `deactivated`, `readable` or `editable`.
- **Reporting sick.** `report_sick(child)` reports the child sick today, and `undo_sick(child)`
  takes it back where Aula tells the child as sick today. `get_sick_report_route(child)` says
  where a child is reported sick:
  - `AULA`: in Aula's presence module, where the guardian's dashboard may change `report_sick`.
    Aula then informs the daycare or after-school staff only, never the school, and takes the
    report back by itself the next day.
  - `TABULEX`: otherwise, where the login has IST's widget into Tabulex. It is known, but not
    supported yet: reporting sick raises `SickReportRouteNotSupportedError`.
  - `NONE`: otherwise. Reporting sick raises `NoSickReportRouteError`.

  Telling the school is a message to the teachers, a separate step.
- **Vacation ("Ferie/fri").** `get_vacations(children)` lists the vacations registered;
  `add_vacation(children, start, end, comment="")` registers one, whole days from `start` to
  `end`: the start today or later, the end at most a year after it, the comment at most 250
  characters; `delete_vacation(vacation_id)` deletes one of the login's children's, where Aula
  lets it be changed.
- **Vacation requests ("Ferieanmodning").** `get_vacation_requests(children)` lists the
  institutions' requests, each with `missing_answer` and its `response_deadline`;
  `get_vacation_request(response_id)` reads one with its answer as it stands; and
  `answer_vacation_request(response_id, days, comment="")` answers it, for each weekday of its
  period from today whether the child comes, with entry and exit times where the request asks
  for them, while its deadline has not passed.
- **Messages.** `threads_about(child)` gives the threads of the newest page that are about the
  child, the newest first; `reply(thread_id, text)` sends plain text to everyone still in a
  thread, as HTML paragraphs, at most 6600 characters. It never marks a thread read.
- **Probing Tabulex's login.** `probe_tabulex()` follows, once, how IST's Tabulex logs the
  guardian in from Aula, to learn how its parent portal works: it posts the login's Tabulex
  widget's form as Aula's portal does on a desktop, with a new widget token, and follows
  redirects and the forms a page submits by itself, at most 15 steps and only on hosts under
  `ist.dk`, `tabulex.dk` and `tabulex.net`; then it follows the portal's own login the same way,
  with what the first chain left, and reads the scripts of the portal's page it ends at, from
  the portal's own site. It posts nothing else. Its report, kept as `tabulex_probe`, tells each
  step's method, host, path, the names of its query and form fields, its status, where it
  redirected, the names and domains of the cookies set, and of a page that ends a chain: its
  forms' fields by name and type, the scripts it loads, its own code with every string masked
  but an address's host and path, and a meta refresh; and the full text of the portal's own
  scripts. Never a value of a token, cookie or field, nor any text of a page.
- **The child's picture.** `get_profile_picture(child)` reads the child's profile picture anew:
  its `url` expires within about an hour.

## What Aula sends

A client keeps the newest answer to each request it sends Aula and its widgets, with its headers
and when it came, and the newest failure of each request that failed - an error's status, or an
error in place of an answer, such as a timeout - even where a later answer succeeded. It keeps
them in memory only, 200 answers and 50 failures at most, and never a request's headers nor a
write. To see
what Aula sends, read everything once and take the answers with who someone is replaced:

```python
failed = await client.read_everything(start, end)  # what could not be read, and why
answers = client.responses(key)  # key: bytes kept secret, the same each time
```

`answers` holds Aula's API version, each request with its answer, and the type at each place of
each kind of answer, to see where Aula has changed. All the answers say is replaced, but how they
are built, so that they can be shared in public: every value gets another of the same length and
kinds of characters, the same one wherever it is and for as long as the key is the same, so that
what belongs together still does.

- Every word of every text, word by word, with capitals where it has them: names, messages,
  titles, notes and the rest.
- Ids, under their keys - an institution's and a municipality's code among them - and inside texts
  and links, and numbers that are known ids.
- E-mail addresses, phone numbers and CPR numbers anywhere, and addresses under their keys.
- The site of every link but Aula's and its widgets', the words of its path, and its query, as it
  can sign the link.

Kept is what tells how an answer is built: the keys; the values of a kind Aula names, such as a
message's type, a notification's area, a role or a status; names in code such as
`NewMessagePrivateInbox`; HTML's tags; dates and times; and numbers that are no ids. The path and
query of a request the client sends are kept but for their ids.

The MitID username and every token the client holds are hidden wherever they stand, as is what
a request for a token answers, and any value under a key of a secret, a cookie among them, or that
looks like a token: a text becomes as many "x", a number as many 9s.

The messages of every thread on the newest page are read, but not those of a thread Aula marks
sensitive, which the client never reads.

`client.anomalies(since=None)` names what Aula sent that the client does not know or could not
read, each `Anomaly` once with its `kind`, its `detail` and when it was `last_seen`, the latest
first: a notification of an unknown area, an answer that could not be read, an answer in a shape
other than the one known (`docs/aula-shapes.md`), a version of Aula's API the client was not made
for, met again at each login while it lasts. None tells any of Aula's data,
so a caller can show them and ask for the answers when Aula changes; `since`, a time with its zone,
leaves out what was not met again since. A later minor version may add a kind, never rename or
remove one, so a caller handles a kind it does not know.

`client.read(method, params, key, reveal=False, body=None)` asks one method of Aula's API that
only gets, and gives its answer as `responses` gives one. `aula_connect.methods` lists every
method known to exist, and how each is asked (`docs/aula-methods.md`). A listed method is asked with its verb: GET, or POST with `body` as
JSON, such as `calendar.getEventsByProfileIdsAndResourceIds`. One not listed is asked with GET,
or POST where `body` is given, where it is named as one that gets, `<area>.get<What>` or
`<area>.find<What>`. `reveal` keeps the values under the keys it names as Aula sent them, such as
`["widgetCategory"]` to see a field of a module not known yet, or the whole answer with `True`;
the MitID username and every token are hidden all the same. What is revealed is no longer
anonymous: share it only in private. It raises `MethodRefusedError`, asking Aula nothing, for a
method that changes Aula, hands out a token, or gets the text of messages or secure documents,
whatever the case of its name; for a listed method asked with the other verb; and for `params`
or a `body` that name a method or a token.

`aula_connect.testing` has a simulated Aula for tests, on local test servers:
`SimulatedAulaLogin` answers the whole login chain - Aula's OAuth, UniLogin, NemLog-in and a
simulated MitID - and `SimulatedAulaApi` Aula's API and its widgets, with the data a test gives
it, and keeps what the writes above change, refusing a body Aula's portal would not send as Aula
does, with HTTP 400 and code 40. `SimulatedTabulex` answers IST's and Tabulex's login chain
under made-up host names, reached through its own `session()` only. Each checks the cookies, tokens and proofs the real one checks, and takes a
`mitid_connect.testing.Network` that gives each answer a latency and fails a share of them, for
stress tests.

## Origin and licence

The login and API client come from the Home Assistant integration
[HairingX/aula](https://github.com/HairingX/aula), a fork of
[scaarup/aula](https://github.com/scaarup/aula), and are licensed as it is: GNU GPL v3.0 or later
(`LICENSE`). The MitID login started as the Aula login client by mchrdk. MitID itself is reached
through [mitid_connect](https://github.com/HairingX/mitid_connect).
