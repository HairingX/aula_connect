"""Text that can be logged, with Aula's and MitID's secrets taken out."""

from __future__ import annotations

import re

# Aula takes its access token in the URL, and requests puts the URL in its errors; the OAuth
# redirect carries the authorization code. A value is taken out where it is a parameter
# (code=...) or a JSON or text field (code: "..."), not where a word only follows the name, as in
# "status code: 400".
_SECRETS = (
    re.compile(r"(?i)\b((?:access_|refresh_|id_)?token|code|password)=[^&\s\"',)]+"),
    re.compile(r"(?i)([\"'](?:(?:access_|refresh_|id_)?token|code|password)[\"']\s*:\s*[\"'])[^\"']*"),
    re.compile(r"(?i)\b((?:(?:access_|refresh_|id_)?token|password)\s*:\s*[\"']?)[^\s\"',)]+"),
)


def redact(value: object) -> str:
    """The text of a URL, a message or an error, with every token, code and password replaced by REDACTED."""
    text = str(value)
    text = _SECRETS[0].sub(r"\1=REDACTED", text)
    for pattern in _SECRETS[1:]:
        text = pattern.sub(r"\1REDACTED", text)
    return text
