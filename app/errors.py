"""Domain exceptions."""


class GeospatialFileError(Exception):
    """The uploaded file is unreadable / structurally invalid (maps to HTTP 422)."""


class UnsupportedFileTypeError(Exception):
    """The file extension is not one we accept (maps to HTTP 415)."""


class FileTooLargeError(Exception):
    """The upload exceeded the configured size limit (maps to HTTP 413)."""
