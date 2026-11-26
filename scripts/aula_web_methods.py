"""Compare the catalog with the methods Aula's own web app asks: python scripts/aula_web_methods.py [JSON]

Fetches the web app's public scripts, with no login, prints what the catalog says otherwise, and
writes every method the web app asks, with its verbs, to JSON where given.
"""

import json
import sys
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from aula_connect.web_methods import PORTAL, differences, methods, scripts


def fetch(url: str) -> str:
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as response:
        return response.read().decode("utf-8", "replace")


found = methods(fetch(urljoin(PORTAL, path)) for path in scripts(fetch(PORTAL)))
print("\n".join(differences(found)))
if sys.argv[1:]:
    with open(sys.argv[1], "w", encoding="utf-8") as file:
        json.dump({name: sorted(verbs) for name, verbs in sorted(found.items())}, file, indent=1)
