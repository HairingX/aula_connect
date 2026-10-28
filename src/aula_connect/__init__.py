"""Client for the Danish school platform Aula: MitID login, and the children's data as typed models."""

from importlib.metadata import PackageNotFoundError, version

from .api.models.aula_parser import set_time_zone
from .client import AulaClient
from .login import AulaLoginClient

try:
    __version__ = version("aula_connect")
except PackageNotFoundError:  # pragma: no cover - only in a checkout that is not installed
    __version__ = "0.0.0"

__all__ = ["AulaClient", "AulaLoginClient", "__version__", "set_time_zone"]
