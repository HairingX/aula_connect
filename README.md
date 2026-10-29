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

`aula_connect.testing` has a simulated Aula for tests, on local test servers:
`SimulatedAulaLogin` answers the whole login chain - Aula's OAuth, UniLogin, NemLog-in and a
simulated MitID - and `SimulatedAulaApi` Aula's API and its widgets, with the data a test gives
it. Each checks the cookies, tokens and proofs the real one checks.

## Origin and licence

The login and API client come from the Home Assistant integration
[HairingX/aula](https://github.com/HairingX/aula), a fork of
[scaarup/aula](https://github.com/scaarup/aula), and are licensed as it is: GNU GPL v3.0 or later
(`LICENSE`). The MitID login started as the Aula login client by mchrdk. MitID itself is reached
through [mitid_connect](https://github.com/HairingX/mitid_connect).
