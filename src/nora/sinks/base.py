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

    def __init__(self, cfg: OmegaConf):
        self.cfg = cfg

    @abstractmethod
    def write(self, paper: Paper) -> WriteResult:
        """Write a paper to this backend, notes included.
        """

    def __repr__(self):
        return f"{self.__class__.__name__}()"
