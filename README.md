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

## What Aula sends

A client keeps the newest answer to each request it sends Aula and its widgets, with its headers
and when it came, and the newest failure of each request that failed - an error's status, or an
error in place of an answer, such as a timeout - even where a later answer succeeded. It keeps
them in memory only, 200 answers and 50 failures at most, and never a request's headers. To see
what Aula sends, read everything once and take the answers with who someone is replaced:

```python
failed = await client.read_everything(start, end)  # what could not be read, and why
answers = client.responses(key)  # key: bytes kept secret, the same each time
```

`answers` holds Aula's API version, each request with its answer, and the type at each place of
each kind of answer, to see where Aula has changed. Every value that tells who someone is gets
another of the same length and kinds of characters, the same one wherever it is and for as long as
the key is the same, so that what belongs together still does:

- ids, under their keys and inside texts and links, and numbers that are known ids;
- names, word by word, under their keys and, written with a capital, inside every text;
- e-mail addresses, phone numbers and CPR numbers anywhere, and addresses under their keys;
- the query of every link, as it can sign it.

The MitID username and every token the client holds are hidden wherever they stand, as is what
a request for a token answers, and any value under a key of a secret, a cookie among them, or that
looks like a token: a text becomes as many "x", a number as many 9s.

Dates, times, other numbers and the rest of each text are kept. A name Aula gives under no key of
a name, such as another child's in a message, is kept with them, so the answers are still personal
data: share them only with who needs them. The messages of every thread on the newest page are
read, but not those of a thread Aula marks sensitive, which the client never reads.

`client.anomalies(since=None)` names what Aula sent that the client does not know or could not
read, each `Anomaly` once with its `kind`, its `detail` and when it was `last_seen`, the latest
first: a notification of an unknown area, an answer that could not be read, a version of Aula's API
the client was not made for. None tells any of Aula's data, so a caller can show them and ask for
the answers when Aula changes; `since` leaves out what was not met again lately.
`client.read(method,
params, key)` asks one method of Aula's API that only gets, named `<area>.get<What>`, and gives its
answer as `responses` gives one; the messages of a thread are never asked this way.

`aula_connect.testing` has a simulated Aula for tests, on local test servers:
`SimulatedAulaLogin` answers the whole login chain - Aula's OAuth, UniLogin, NemLog-in and a
simulated MitID - and `SimulatedAulaApi` Aula's API and its widgets, with the data a test gives
it. Each checks the cookies, tokens and proofs the real one checks, and takes a
`mitid_connect.testing.Network` that gives each answer a latency and fails a share of them, for
stress tests.

## Origin and licence

The login and API client come from the Home Assistant integration
[HairingX/aula](https://github.com/HairingX/aula), a fork of
[scaarup/aula](https://github.com/scaarup/aula), and are licensed as it is: GNU GPL v3.0 or later
(`LICENSE`). The MitID login started as the Aula login client by mchrdk. MitID itself is reached
through [mitid_connect](https://github.com/HairingX/mitid_connect).
