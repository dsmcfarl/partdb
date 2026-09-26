class PartDBError(Exception):
    """Base class for expected PartDB domain errors."""


class LocationNotFound(PartDBError):
    pass


class PartNotFound(PartDBError):
    pass


class LocationNotEmpty(PartDBError):
    pass


class DuplicateLocation(PartDBError):
    pass


class EmbeddingUnavailable(PartDBError):
    pass
