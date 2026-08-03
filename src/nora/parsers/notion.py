import re
from omegaconf import OmegaConf
from typing import Dict, List, Optional

from nora.paper import Paper, normalize_abstract
from nora.sinks.base import SinkError
from nora.sinks.notion import NotionLibrary


__all__ = [
    'NotionSource', 'decode_property', 'identifiers_from_url', 'page_title']


# The Notion reading status meaning a paper has been read. Every other
# state - 'Hot', 'In progress', 'Organize resource', ... - is a way of not
# having finished it yet, and NoRA only tracks the distinction
DONE_STATUS = 'done'

# Identifiers recoverable from the URL of a paper, for a Notion database
# that has no DOI or arXiv property of its own
ARXIV_URL = re.compile(
    r'arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7})',
    re.IGNORECASE)
DOI_URL = re.compile(
    # `/doi/10.1029/...` with nothing in between is what Wiley and AGU
    # serve, so the abs/full/pdf segment cannot be required
    r'(?:doi\.org/|dx\.doi\.org/|/doi/(?:[a-z]+/)?)(?P<id>10\.\d{4,9}/[^\s?#]+)',
    re.IGNORECASE)


def decode_property(value: Dict, names: Dict[str, str]=None):
    """Turn one Notion property value into a Python one.

    Notion wraps every value in its type, and a column's type is the
    user's to change - a Group may be a select today and a relation
    tomorrow - so every type NoRA might meet is handled rather than the
    one it expects. `names` maps the page id of a related page to its
    title, since a relation only ever comes back as ids.
    """
    if not isinstance(value, dict):
        return None

    kind = value.get('type')
    names = names or {}

    if kind in ('title', 'rich_text'):
        return ''.join(x.get('plain_text', '') for x in value[kind]) or None

    if kind == 'select':
        return (value['select'] or {}).get('name')

    if kind == 'status':
        return (value['status'] or {}).get('name')

    if kind == 'multi_select':
        return [x['name'] for x in value['multi_select']]

    if kind == 'relation':
        titles = []
        for related in value['relation']:
            page_id = related.get('id')
            if not page_id:
                continue
            try:
                # Indexed rather than `.get`, so that a mapping which
                # resolves ids on demand gets the chance to
                title = names[page_id]
            except KeyError:
                continue
            if title:
                titles.append(title)
        return titles

    if kind in ('url', 'email', 'phone_number'):
        return value[kind]

    if kind == 'number':
        return value['number']

    if kind == 'checkbox':
        return value['checkbox']

    if kind == 'date':
        return (value['date'] or {}).get('start')

    if kind == 'people':
        return [x.get('name') for x in value['people'] if x.get('name')]

    if kind == 'formula':
        return decode_property(value['formula'], names)

    if kind == 'rollup':
        rollup = value['rollup']
        if rollup.get('type') == 'array':
            return [decode_property(x, names) for x in rollup['array']]
        return decode_property(rollup, names)

    return None


def identifiers_from_url(url: Optional[str]):
    """The DOI and arXiv id a paper's URL gives away, if any.

    A Notion database that never recorded them still points at the paper,
    and an arxiv.org or doi.org link carries the identifier NoRA needs to
    recognize the Obsidian note of the same paper.
    """
    if not url:
        return None, None

    arxiv = ARXIV_URL.search(url)
    doi = DOI_URL.search(url)
    return (
        doi.group('id').rstrip('.').lower() if doi else None,
        arxiv.group('id').lower() if arxiv else None)


def page_title(page: Dict):
    """The title of a Notion page, whatever its title column is called.

    A related page is reached by id, so which of its properties holds the
    name is not known in advance - only that exactly one of them is of
    type `title`.
    """
    for value in (page.get('properties') or {}).values():
        if isinstance(value, dict) and value.get('type') == 'title':
            return decode_property(value)
    return None


class _RelatedNames(dict):

    """Page id to title, filling itself in as unknown ids turn up.

    Authors, venues and topics are read in bulk, one query per database.
    Anything else a paper relates to - your Projects above all - is
    resolved a page at a time and remembered, which costs one request per
    distinct project rather than one per paper, and needs no database id
    in your config.
    """

    def __init__(self, library):
        super().__init__()
        self.library = library

    def __missing__(self, page_id):
        """Resolve a related page, or stop the sync.

        Failing to reach a page is not an answer about it. Treating it as
        'this project does not exist' would strip the project from every
        note that has it, because Notion owns that field and absence is
        deletion for an owner - so a dropped connection would quietly
        undo your curation. Nothing has been written by the time relations
        are resolved, so refusing here costs a run and no data.
        """
        try:
            page = self.library.retrieve_page_from_id(page_id)
        except Exception as e:
            raise SinkError(
                f"could not read the related Notion page {page_id}, so the "
                f"projects of your papers cannot be trusted ({e})")

        # A page that reads fine but carries no title is a real answer,
        # and simply relates to nothing nameable
        title = page_title(page)
        self[page_id] = title
        return title


class NotionSource:

    """Read the papers of your Notion databases back out as `Paper`s.

    The mirror image of `NotionSink`: where the sink turns a `Paper` into
    pages, this turns pages into `Paper`s, so that everything downstream -
    the Obsidian sink above all - needs to know nothing about Notion.
    """

    name = 'notion'

    def __init__(self, cfg: OmegaConf, verbose: bool=True):
        self.cfg = cfg
        self.verbose = verbose
        self.library = NotionLibrary(cfg)
        self._names = None
        self._pages = None

    def _related_names(self):
        """Map the page id of every author, venue and topic to its title.

        Notion hands over relations as page ids only. Resolving them one
        by one would mean a request per author of every paper, against an
        API that allows about three a second, so each database is read
        once instead.
        """
        if self._names is not None:
            return self._names

        self._names = _RelatedNames(self.library)
        databases = [
            (self.library.get_people, self.cfg.person_keys['name']),
            (self.library.get_venues, self.cfg.venue_keys['name']),
            (self.library.get_topics, self.cfg.topic_keys['name'])]

        for getter, name_property in databases:
            for page in getter():
                title = decode_property(
                    page.get('properties', {}).get(name_property, {}))
                if title:
                    self._names[page['id']] = title

        if self.verbose:
            print(f"🔗 Resolved {len(self._names)} authors, venues and topics")

        return self._names

    def to_paper(self, page: Dict):
        """Build a `Paper` from one page of your Notion Papers database.
        """
        keys = self.cfg.paper_keys
        properties = page.get('properties', {})
        names = self._related_names()

        def value(key, default=None):
            """The value of one of the configured properties. A key you
            have not configured, or a column you have since renamed or
            removed, is simply absent rather than fatal.
            """
            name = keys.get(key)
            if not name or name not in properties:
                return default
            decoded = decode_property(properties[name], names)
            return default if decoded is None else decoded

        def first(key):
            decoded = value(key)
            if isinstance(decoded, list):
                return decoded[0] if decoded else None
            return decoded

        title = first('name')
        if not title:
            return None

        topics = value('topics', [])
        if not isinstance(topics, list):
            topics = [topics]

        # Which project a paper serves is yours to set, in Notion, and the
        # sync is the only thing that carries it over
        projects = value('projects', [])
        if not isinstance(projects, list):
            projects = [projects]

        authors = value('authors', [])
        if not isinstance(authors, list):
            authors = [authors]

        # Only 'Done' means read. Every other state of your Notion status
        # is a flavour of not yet
        status = first('to_read')
        to_read = str(status).strip().lower() != DONE_STATUS

        url = first('url')
        doi, arxiv = identifiers_from_url(url)

        # A database that does record them is believed over the URL
        doi = first('doi') or doi
        arxiv = first('arxiv') or arxiv

        year = first('year')

        return Paper(
            title=title,
            authors=[x for x in authors if x],
            abstract=normalize_abstract(first('abstract')),
            year=int(year) if isinstance(year, (int, float)) else None,
            venue=first('venue'),
            url=url,
            topics=[x for x in topics if x],
            projects=[x for x in projects if x],
            to_read=to_read,
            doi=str(doi) if doi else None,
            arxiv_id=str(arxiv) if arxiv else None,
            source='notion',
            source_id=page.get('id'),
            date_added=(page.get('created_time') or '')[:10] or None)

    def pages(self):
        """Every page of your Notion Papers database, read once.
        """
        if self._pages is None:
            self._pages = self.library.get_papers()
            if self.verbose:
                print(f"📖 Read {len(self._pages)} papers from Notion")
        return self._pages

    def __iter__(self):
        """Every paper of your Notion library, one at a time.
        """
        for page in self.pages():
            paper = self.to_paper(page)
            if paper is not None:
                yield paper

    def __len__(self):
        return len(self.pages())

    def __repr__(self):
        return f"{self.__class__.__name__}()"
