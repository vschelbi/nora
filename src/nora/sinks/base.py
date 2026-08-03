from abc import ABC, abstractmethod
from dataclasses import dataclass
from omegaconf import OmegaConf

from nora.paper import Paper


__all__ = [
    'CREATED', 'SKIPPED', 'UPDATED', 'SinkError', 'WriteResult', 'Sink']


# Outcomes of writing a paper to a backend
CREATED = 'created'
SKIPPED = 'skipped'
UPDATED = 'updated'


class SinkError(RuntimeError):

    """Raised when a backend could not write a paper. Callers uploading
    many papers are expected to catch this and carry on with the next
    one, rather than interrupting the whole upload.
    """


@dataclass
class WriteResult:

    """What a backend did with a paper.
    """

    status: str
    ref: str = ''  # Notion page id, or path of the Obsidian note
    message: str = ''


class Sink(ABC):

    """Base class for a NoRA write backend.

    A sink receives fully-normalized `Paper` objects and is responsible
    for creating the corresponding entry in its own storage, notes
    included. Sinks do not print progress: they return a `WriteResult`
    and let the caller report it.
    """

    name = ''

    def __init__(self, cfg: OmegaConf, authoritative=()):
        self.cfg = cfg

        # Logical `paper_keys` names the caller is the source of truth
        # for. A backend that merges with what it already holds honours
        # these; one that only ever creates has nothing to merge and may
        # ignore them
        self.authoritative = frozenset(authoritative)

    @abstractmethod
    def write(self, paper: Paper) -> WriteResult:
        """Write a paper to this backend, notes included.
        """

    def has_paper(self, paper: Paper):
        """Whether this backend already holds a paper.

        `None` means it cannot tell cheaply, which callers must read as
        'do not assume it is missing' rather than as a no.
        """
        return None

    def __repr__(self):
        return f"{self.__class__.__name__}()"
