# aula_connect

A Python client for [Aula](https://www.aula.dk), the Danish school and institution platform. It
logs in through MitID - with the MitID app's QR code or code - and reads the children's
profiles, daily overviews (presence), calendars, birthdays, messages, notifications, weekly
plans (Meebook, EasyIQ, MinUddannelse) and newsletters into typed models.

It is the library the Home Assistant integration
[ha_aula_connect](https://github.com/HairingX/ha_aula_connect) is built on.

```python
from aula_connect import AulaClient, AulaLoginClient

login = AulaLoginClient(mitid_username="...")   # approve in the MitID app
tokens = login.authenticate()["tokens"]
client = AulaClient(
    access_token=tokens["access_token"],
    refresh_token=tokens["refresh_token"],
    expires_at=tokens["expires_at"],
    mitid_username="...",
    login_client=login,
)
data = client.login()
```

## Origin and licence

The login and API client come from the Home Assistant integration
[HairingX/aula](https://github.com/HairingX/aula), a fork of
[scaarup/aula](https://github.com/scaarup/aula), and are licensed as it is: GNU GPL v3.0 or later
(`LICENSE`). The MitID login started as the Aula login client by mchrdk. MitID itself is reached
through [mitid_connect](https://github.com/HairingX/mitid_connect).
