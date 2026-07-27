import re
import arxiv
from omegaconf import OmegaConf

from nora.paper import Paper, normalize_abstract
from nora.utils.venues import parse_venue


__all__ = ['ArxivItem', 'ArxivQueryError']


class ArxivQueryError(RuntimeError):
    """Raised when the arxiv database could not be queried, or returned
    no result. Callers only using arxiv to enrich already-known metadata
    are expected to catch this and carry on.
    """


# Documentation: http://lukasschwab.me/arxiv.py/index.html

# Create a Client to wrap the requests. In particular, the Client
# ensures you do not make more than 1 request every 3 seconds, which is
# the maximum request frequency explicitly required by arxiv
CLIENT = arxiv.Client(page_size=100, delay_seconds=3, num_retries=3)


class ArxivItem:

    def __init__(
            self,
            arxiv_id: str=None,
            title: str=None,
            max_results: int=10,
            cfg_venues: OmegaConf=None):
        """Object to query a paper from arxiv.

        :param arxiv_id: str
            Arxiv identifier, or arxiv url, from which the identifier
            will be parsed
        :param title: str
            Title - or portion of the title - of the paper. The arxiv
            database will be queried and the top 10 results will be
            returned
        """
        assert arxiv_id is not None or title is not None, \
            "Please provide an arxiv identifier or a paper title"

        self.cfg_venues = cfg_venues

        if arxiv_id is not None:
            arxiv_id = str(arxiv_id)

            # Parse arxiv id from a url
            if 'arxiv.org' in arxiv_id:
                arxiv_id = arxiv_id.split('arxiv.org/')[-1].replace('.pdf', '')

            # Check whether arxiv id format before March 2007
            if not bool(re.search(r'[0-9]{4}\.[0-9]', arxiv_id)):
                raise ArxivQueryError(
                    f"The arxiv identifier '{arxiv_id}' does not follow the "
                    f"arxiv format defined for articles published after March "
                    f"2007. At the moment, only articles following this "
                    f"pattern are supported. Please refer to:"
                    f"https://info.arxiv.org/help/arxiv_identifier.html")

            # Isolate the YYMM.NNNNN sequence
            arxiv_id = arxiv_id.split('/')[-1]

            # Sometimes trailing 0s are lost in the process. It is
            # possible to cover these cases as long as the article
            # came out after March 2007:
            # https://info.arxiv.org/help/arxiv_identifier.html
            try:
                yymm, numbervv = arxiv_id.split(':')[-1].split('.')
                expected_number_size = 5 if int(yymm) >= 1501 else 4
            except ValueError:
                raise ArxivQueryError(
                    f"The arxiv identifier '{arxiv_id}' could not be parsed")
            if len(numbervv) < expected_number_size:
                numbervv += '0' * (expected_number_size - len(numbervv))
                arxiv_id = f"{yymm}.{numbervv}"

            self.id = arxiv_id
            try:
                results = list(CLIENT.results(arxiv.Search(id_list=[arxiv_id])))
            except Exception as e:
                raise ArxivQueryError(
                    f"Could not query the arxiv database for "
                    f"id='{arxiv_id}': {e}")
            if len(results) == 0:
                raise ArxivQueryError(
                    f"Could not find paper with id='{arxiv_id}'")
            self._item = results[0]
            return

        if title is not None:
            results = list(CLIENT.results(arxiv.Search(
                query=f"ti:{title}", max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance)))
            results = [res for res in results if title in res.title]
            if len(results) == 0:
                raise ArxivQueryError(
                    f"Could not find paper with title='{title}'")
            if len(results) > 1:
                raise ArxivQueryError(
                    f"Found multiple papers matching title='{title}'. "
                    f"Please refine among the following:\n" +
                    '\n'.join([res.title for res in results]))
            self.id = results[0].entry_id.split('/')[-1].replace('.pdf', '')
            self._item = results[0]

    @classmethod
    def from_result(cls, result, cfg_venues: OmegaConf=None):
        """Build an item from an already-retrieved arxiv result, without
        querying the arxiv database again.
        """
        item = cls.__new__(cls)
        item.cfg_venues = cfg_venues
        item.id = result.entry_id.split('/')[-1].replace('.pdf', '')
        item._item = result
        return item

    @property
    def title(self):
        return self._item.title

    @property
    def authors(self):
        return [x.name for x in self._item.authors]

    @property
    def abstract(self):
        return self._item.summary

    @property
    def venue(self):
        # Search venue in 'journal_ref'
        venue = parse_venue(self._item.journal_ref, self.cfg_venues)
        if venue is not None:
            return venue

        # Search venue in 'comment'
        venue = parse_venue(self.notes, self.cfg_venues)
        if venue is not None:
            return venue

        return self._item.journal_ref

    @property
    def year(self):
        return self._item.published.year

    @property
    def notes(self):
        return self._item.comment

    @property
    def url(self):
        return f"http://arxiv.org/abs/{self.id}"

    @property
    def doi(self):
        return self._item.doi

    def to_paper(self):
        """Convert to the source-agnostic representation consumed by the
        sinks.
        """
        return Paper(
            title=self.title,
            authors=self.authors,
            abstract=normalize_abstract(self.abstract),
            year=self.year,
            venue=self.venue,
            url=self.url,
            topics=[],
            to_read=True,
            notes=self.notes or '',
            notes_format='text',
            doi=self.doi,
            arxiv_id=self.id,
            item_type='preprint',
            source='arxiv',
            source_id=self.id)

    def __repr__(self):
        info = [
            f"{key}={getattr(self, key)}"
            for key in ['id', 'title', 'authors']]
        return f"{self.__class__.__name__}({', '.join(info)})"
