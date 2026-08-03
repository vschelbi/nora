from dataclasses import dataclass, field
from typing import List, Optional


__all__ = ['Paper', 'format_author_name', 'normalize_abstract']


def format_author_name(first: str, last: str):
    """Build a display name from the first and last names returned by the
    Zotero API.
    """
    return f"{first} {last}".strip()


def normalize_abstract(abstract: Optional[str]):
    """Abstracts scraped from PDFs come with hard line breaks and
    hyphenated word splits, which we clean up here.
    """
    if abstract is None:
        return None
    return ' '.join(abstract.split('\n')).replace('- ', '')


@dataclass
class Paper:

    """Source-agnostic representation of a paper. Produced by the
    parsers, consumed by the sinks. This is the only vocabulary shared
    between the two, so neither needs to know about the other.
    """

    # The only required field: a paper without a title is meaningless
    title: str

    # Core metadata
    authors: List[str] = field(default_factory=list)
    abstract: Optional[str] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    url: Optional[str] = None
    topics: List[str] = field(default_factory=list)
    to_read: bool = True

    # Which of your projects a paper serves. No reference manager knows
    # this, so the parsers leave it empty and only a sync from a backend
    # you curate by hand - Notion - ever fills it
    projects: List[str] = field(default_factory=list)

    # Free text notes, and the format they are written in. Zotero child
    # notes are HTML, while the arXiv 'comment' field is plain text, so
    # sinks cannot guess and must be told
    notes: str = ''
    notes_format: str = 'text'  # 'html', 'markdown' or 'text'

    # Identifiers
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    item_type: Optional[str] = None

    # Provenance
    source: str = ''  # 'zotero', 'arxiv', 'url' or 'identifier'
    source_id: Optional[str] = None
    date_added: Optional[str] = None  # ISO-8601
