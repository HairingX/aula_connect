"""The errors Aula's API client raises."""

class ParseError(Exception):
    """
    Exception raised when parsing the response from the server fails.
    """

class MethodRefusedError(ValueError):
    """A method of Aula's API that is not asked for the caller: one that does more than get, or
    that gets what may be marked sensitive."""

class AulaCredentialError(Exception):
    """
    Exception raised when the credentials were rejected.
    """

class AulaApiError(Exception):
    """
    Exception raised for non-credential API errors (e.g., unexpected HTTP status codes).
    Unlike AulaCredentialError, this does NOT trigger MitID re-authentication.
    """

class NoSickReportRouteError(Exception):
    """No way is known to report the child sick: Aula's presence module does not let its guardian,
    and no widget of the login offers it."""

class SickReportRouteNotSupportedError(Exception):
    """The child is reported sick through a widget's own service, which this library cannot use yet."""

    def __init__(self, route: str) -> None:
        """The child is reported sick through `route`."""
        super().__init__(f"The child is reported sick through {route}, which is not supported yet")
        self.route = route

class NoTabulexWidgetError(Exception):
    """The login has no widget of IST's that signs in to Tabulex."""
