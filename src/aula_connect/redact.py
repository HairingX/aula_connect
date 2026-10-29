"""Text that can be logged, with Aula's and MitID's secrets taken out."""

from __future__ import annotations

import re

# Aula takes its access token in the URL, and requests puts the URL in its errors; the OAuth
# redirect carries the authorization code.
_SECRET = re.compile(
    r"(?i)\b(access_token|refresh_token|id_token|token|code|password)(=|[\"']?\s*:\s*[\"']?)[^&\s\"',)]+"
)


def redact(value: object) -> str:
    """The text of a URL, a message or an error, with every token, code and password replaced by REDACTED."""
    return _SECRET.sub(r"\1\2REDACTED", str(value))
