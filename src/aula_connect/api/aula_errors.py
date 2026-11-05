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
