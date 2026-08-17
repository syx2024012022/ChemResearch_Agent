class ChemResearchError(Exception):
    """Base class for expected application errors."""


class InvalidTransitionError(ChemResearchError):
    pass


class SessionNotFoundError(ChemResearchError):
    pass


class DocumentNotFoundError(ChemResearchError):
    pass


class ConcurrentUpdateError(ChemResearchError):
    pass


class EvidenceGroundingError(ChemResearchError):
    pass


class AnalysisUnavailableError(ChemResearchError):
    pass


class ArtifactNotFoundError(ChemResearchError):
    pass
