from nora.paper import Paper, format_author_name, normalize_abstract
from nora.parsers.arxiv import ArxivItem
from nora.parsers.zotero import ZoteroItem
from nora.utils.zotero import ZOTERO_SUPPORTED_TYPES


class FakeArxivAuthor:
    def __init__(self, name):
        self.name = name


class FakeArxivDate:
    year = 2017


class FakeArxivResult:
    entry_id = 'http://arxiv.org/abs/1706.03762v5'
    title = 'Attention Is All You Need'
    summary = 'An abstract.'
    comment = 'Accepted at NeurIPS 2017'
    journal_ref = 'NeurIPS 2017'
    doi = '10.1000/attention'
    published = FakeArxivDate()
    authors = [FakeArxivAuthor('Ashish Vaswani'), FakeArxivAuthor('Noam Shazeer')]


def test_zotero_to_paper_joins_author_names(zotero_item_data):
    paper = ZoteroItem(zotero_item_data).to_paper()

    # The Zotero API returns (firstName, lastName) pairs, sinks expect
    # display names, and this is the only place the two meet
    assert paper.authors == ['Ada Lovelace', 'Alan Turing']
    assert all(isinstance(x, str) for x in paper.authors)


def test_zotero_to_paper_drops_creators_without_a_first_name(zotero_item_data):
    # 'Some Institution' has no firstName and must not become an author
    paper = ZoteroItem(zotero_item_data).to_paper()
    assert 'Some Institution' not in paper.authors


def test_zotero_to_paper_carries_metadata(zotero_item_data):
    paper = ZoteroItem(zotero_item_data).to_paper()

    assert paper.title == 'A Synthetic Paper About Nothing'
    assert paper.year == 2019
    assert paper.doi == '10.1000/synthetic'
    assert paper.arxiv_id == '1706.03762'
    assert paper.item_type == 'conferencePaper'
    assert paper.source == 'zotero'
    assert paper.source_id == 'ABCD1234'
    assert paper.date_added == '2019-07-01T09:00:00Z'

    # Zotero child notes are HTML, and sinks cannot guess that
    assert paper.notes_format == 'html'


def test_arxiv_to_paper():
    paper = ArxivItem.from_result(FakeArxivResult()).to_paper()

    assert paper.authors == ['Ashish Vaswani', 'Noam Shazeer']
    assert isinstance(paper.year, int) and paper.year == 2017
    assert paper.url == 'http://arxiv.org/abs/1706.03762v5'
    assert paper.arxiv_id == '1706.03762v5'
    assert paper.item_type == 'preprint'

    # The arXiv comment field is plain text, unlike Zotero notes
    assert paper.notes_format == 'text'


def test_normalize_abstract():
    # Pinned exactly as the Notion backend used to do it, including the
    # fact that it also eats markdown bullets, so that a later cleanup
    # cannot silently change what gets uploaded
    assert normalize_abstract('multi-\nline abs- tract') == 'multiline abstract'
    assert normalize_abstract('- a bullet') == 'a bullet'
    assert normalize_abstract(None) is None


def test_format_author_name():
    assert format_author_name('Ada', 'Lovelace') == 'Ada Lovelace'
    assert format_author_name('', 'Lovelace') == 'Lovelace'


def test_paper_defaults():
    paper = Paper(title='Only a title')
    assert paper.authors == [] and paper.topics == []
    assert paper.to_read is True
    assert paper.notes == '' and paper.notes_format == 'text'

    # Mutable defaults must not be shared between instances
    Paper(title='a').authors.append('x')
    assert Paper(title='b').authors == []


def test_books_and_blog_posts_are_supported_item_types():
    # A missing comma used to concatenate these into 'blogPostbook',
    # silently dropping every book and blog post from a Zotero upload
    assert 'book' in ZOTERO_SUPPORTED_TYPES
    assert 'blogPost' in ZOTERO_SUPPORTED_TYPES
