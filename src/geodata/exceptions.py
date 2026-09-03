"""Exceptions raised by the geodata query API."""


class GeodataError(Exception):
    """Base class for everything this package raises."""


class NotFound(GeodataError):
    """No record matched the lookup."""


class CountryNotFound(NotFound):
    pass


class StateNotFound(NotFound):
    pass


class CityNotFound(NotFound):
    pass


class LanguageNotFound(NotFound):
    pass


class Ambiguous(GeodataError):
    """The lookup matched more than one record.

    Raised rather than picking arbitrarily: a silent wrong answer in geographic
    data propagates into addresses and shipping.
    """
