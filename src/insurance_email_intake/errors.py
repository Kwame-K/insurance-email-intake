class EmptyEmailError(ValueError):
    """The email has no readable text body."""


class RecordNotFoundError(LookupError):
    """No stored email matches the requested source_id."""


class NotCompletableError(ValueError):
    """Only emails pending information can be completed with overrides."""


class UnderwritingUnavailableError(RuntimeError):
    """The underwriting service could not be reached or returned an error."""
