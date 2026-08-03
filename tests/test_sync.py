import json
import pytest
from pathlib import Path

from nora.paper import Paper
from nora.parsers.notion import (
    NotionSource, decode_property, identifiers_from_url)
from nora.sinks import ObsidianSink
from nora.sinks.base import CREATED, UPDATED
from nora.sinks.obsidian import ObsidianLibrary
from nora.sync import AUTHORITATIVE, SOURCE, sync_from_notion


FIXTURES = Path(__file__).parent / 'fixtures'


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


@pytest.fixture
def notion_pages():
    """A synthetic Notion API response. Deliberately not a real one: no
    real database id, page id or token belongs in a public repository.
    """
    with open(FIXTURES / 'notion_papers.json') as f:
        return json.load(f)


@pytest.fixture
def source(cfg, notion_pages, monkeypatch):
    """A NotionSource reading the fixture instead of the Notion API.
    """
    monkeypatch.setattr(
        'nora.parsers.notion.NotionLibrary', lambda cfg: _FakeLibrary(
            notion_pages))
    cfg.notion.paper_keys.topics = 'Topics / Tags'
    cfg.notion.paper_keys.authors = 'Authors'
    cfg.notion.paper_keys.venue = 'Venue'
    cfg.notion.paper_keys.to_read = 'Reading status'
    return NotionSource(cfg.notion, verbose=False)


class _FakeLibrary:
    """Stands in for NotionLibrary, so that no test needs a token, a
    network or a database.
    """

    def __init__(self, pages):
        self.pages = pages

    def get_papers(self):
        return self.pages['papers']

    def get_people(self):
        return self.pages['people']

    def get_venues(self):
        return self.pages['venues']

    def get_topics(self):
        return self.pages['topics']


# ----------------------------------------------------------------------
#  Reading Notion properties
# ----------------------------------------------------------------------
@pytest.mark.parametrize('value, expected', [
    ({'type': 'title', 'title': [{'plain_text': 'A Paper'}]}, 'A Paper'),
    ({'type': 'rich_text', 'rich_text': []}, None),
    ({'type': 'select', 'select': {'name': 'Hot'}}, 'Hot'),
    ({'type': 'select', 'select': None}, None),
    ({'type': 'status', 'status': {'name': 'Done'}}, 'Done'),
    ({'type': 'status', 'status': None}, None),
    ({'type': 'multi_select', 'multi_select': [{'name': 'a'}]}, ['a']),
    ({'type': 'url', 'url': 'https://x.org'}, 'https://x.org'),
    ({'type': 'number', 'number': 2017}, 2017),
    ({'type': 'checkbox', 'checkbox': False}, False),
    ({'type': 'date', 'date': {'start': '2026-07-27'}}, '2026-07-27'),
    ({'type': 'date', 'date': None}, None),
    # A column type NoRA has never met is not worth crashing over
    ({'type': 'created_by', 'created_by': {}}, None),
])
def test_property_types_are_decoded(value, expected):
    assert decode_property(value) == expected


def test_a_relation_is_resolved_to_its_titles():
    value = {'type': 'relation', 'relation': [{'id': 'a'}, {'id': 'gone'}]}
    # A relation to a page NoRA could not read is dropped rather than
    # turned into a page id nobody can make sense of
    assert decode_property(value, {'a': 'Transformers'}) == ['Transformers']


@pytest.mark.parametrize('url, doi, arxiv', [
    ('https://arxiv.org/abs/1706.03762', None, '1706.03762'),
    ('https://arxiv.org/pdf/2204.07548v2', None, '2204.07548v2'),
    ('https://doi.org/10.1234/abcd', '10.1234/abcd', None),
    ('https://dl.acm.org/doi/abs/10.1145/3292500', '10.1145/3292500', None),
    # A publisher landing page gives away nothing
    ('https://openaccess.thecvf.com/content/paper.pdf', None, None),
    (None, None, None),
])
def test_identifiers_are_recovered_from_a_url(url, doi, arxiv):
    assert identifiers_from_url(url) == (doi, arxiv)


# ----------------------------------------------------------------------
#  Notion pages as papers
# ----------------------------------------------------------------------
def test_a_notion_page_becomes_a_paper(source):
    papers = list(source)
    assert [p.title for p in papers] == [
        'Attention Is All You Need', 'Segment Any Point Cloud', 'No Status Set']

    first = papers[0]
    assert first.authors == ['Ashish Vaswani', 'Noam Shazeer']
    assert first.venue == 'NeurIPS'
    assert first.topics == ['Transformers', '3D vision']
    assert first.year == 2017
    assert first.arxiv_id == '1706.03762'
    assert first.abstract == 'An abstract.'
    assert first.source == 'notion'
    assert first.date_added == '2026-07-27'


def test_only_done_counts_as_read(source):
    done, hot, unset = list(source)

    # 'Hot', 'In progress' and 'Organize resource' are all ways of not
    # having finished a paper
    assert done.to_read is False
    assert hot.to_read is True
    assert unset.to_read is True


def test_topics_are_read_from_a_multi_select_too(source):
    assert list(source)[1].topics == ['3D vision']


def test_the_doi_is_recovered_from_the_url(source):
    assert list(source)[1].doi == '10.1234/abcd'


def test_a_configured_identifier_column_wins_over_the_url(cfg, source):
    # A Notion database that does record the DOI is believed over whatever
    # the URL happens to look like
    source.cfg.paper_keys.doi = 'DOI'
    page = dict(source.library.pages['papers'][0])
    page['properties'] = dict(page['properties'])
    page['properties']['DOI'] = {
        'type': 'rich_text', 'rich_text': [{'plain_text': '10.9999/real'}]}

    assert source.to_paper(page).doi == '10.9999/real'


# ----------------------------------------------------------------------
#  Syncing into a vault
# ----------------------------------------------------------------------
def test_sync_creates_the_papers_your_vault_does_not_have(
        cfg, source, obsidian_cfg, monkeypatch):
    monkeypatch.setattr('nora.sync.NotionSource', lambda cfg, verbose: source)
    cfg.obsidian = obsidian_cfg

    counts = sync_from_notion(cfg, to=('obsidian',), verbose=False)

    vault = Path(obsidian_cfg.vault_path)
    assert counts == {'obsidian': {CREATED: 3}}
    assert (vault / 'Papers' / 'Attention Is All You Need.md').is_file()
    # Authors, venues and topics get their notes, so the graph works
    assert (vault / 'People' / 'Ashish Vaswani.md').is_file()
    assert (vault / 'Venues' / 'NeurIPS.md').is_file()
    assert (vault / 'Topics' / 'Transformers.md').is_file()


def test_sync_can_leave_papers_you_do_not_have_alone(
        cfg, source, obsidian_cfg, monkeypatch):
    monkeypatch.setattr('nora.sync.NotionSource', lambda cfg, verbose: source)
    cfg.obsidian = obsidian_cfg

    counts = sync_from_notion(cfg, to=('obsidian',), create_missing=False, verbose=False)

    assert counts == {'obsidian': {}}
    assert not list((Path(obsidian_cfg.vault_path) / 'Papers').glob('*.md'))


def test_a_dry_run_writes_nothing(cfg, source, obsidian_cfg, monkeypatch):
    monkeypatch.setattr('nora.sync.NotionSource', lambda cfg, verbose: source)
    cfg.obsidian = obsidian_cfg

    counts = sync_from_notion(cfg, to=('obsidian',), dry_run=True, verbose=False)

    assert counts == {CREATED: 3}
    assert not list((Path(obsidian_cfg.vault_path) / 'Papers').glob('*.md'))


def test_sync_carries_the_reading_status_notion_owns(
        cfg, source, obsidian_cfg, monkeypatch):
    monkeypatch.setattr('nora.sync.NotionSource', lambda cfg, verbose: source)
    cfg.obsidian = obsidian_cfg

    # The paper is already in the vault, unread, from an arXiv upload
    paper = Paper(title='Attention Is All You Need', arxiv_id='1706.03762')
    path = ObsidianSink(obsidian_cfg).write(paper).ref

    counts = sync_from_notion(cfg, to=('obsidian',), verbose=False)

    frontmatter, _ = ObsidianLibrary._split_note(read(path))
    assert counts['obsidian'][UPDATED] == 1
    # An ordinary upload may not touch the reading status; a sync must
    assert frontmatter['reading_status'] == 'Done'
    assert frontmatter['topics'] == [
        '[[Topics/Transformers|Transformers]]',
        '[[Topics/3D vision|3D vision]]']


def test_a_sync_may_clear_a_topic_you_removed_in_notion(
        cfg, source, obsidian_cfg, monkeypatch):
    monkeypatch.setattr('nora.sync.NotionSource', lambda cfg, verbose: source)
    cfg.obsidian = obsidian_cfg

    # 'No Status Set' has no topics in Notion, and this note has one
    paper = Paper(title='No Status Set', topics=['Removed Since'])
    path = ObsidianSink(obsidian_cfg).write(paper).ref

    sync_from_notion(cfg, to=('obsidian',), verbose=False)

    frontmatter, _ = ObsidianLibrary._split_note(read(path))
    # Absence is not deletion for an upload that knows nothing, but it is
    # for the owner of the field: otherwise a topic could never be removed
    assert frontmatter['topics'] == []


def test_a_sync_leaves_your_projects_and_your_writing_alone(
        cfg, source, obsidian_cfg, monkeypatch):
    monkeypatch.setattr('nora.sync.NotionSource', lambda cfg, verbose: source)
    cfg.obsidian = obsidian_cfg

    paper = Paper(title='Attention Is All You Need', arxiv_id='1706.03762')
    path = ObsidianSink(obsidian_cfg).write(paper).ref

    frontmatter, body = ObsidianLibrary._split_note(read(path))
    frontmatter['projects'] = ['[[Projects/Thesis|Thesis]]']
    with open(path, 'w', encoding='utf-8') as f:
        f.write(
            f"---\n{ObsidianLibrary._dump_frontmatter(frontmatter)}---\n\n"
            f"{body}\n## My own thoughts\n\nDo not delete me.\n")

    sync_from_notion(cfg, to=('obsidian',), verbose=False)

    text = read(path)
    frontmatter, _ = ObsidianLibrary._split_note(text)
    assert frontmatter['projects'] == ['[[Projects/Thesis|Thesis]]']
    assert 'Do not delete me.' in text


def test_topics_become_tags_when_you_ask_for_them(
        cfg, source, obsidian_cfg, monkeypatch):
    monkeypatch.setattr('nora.sync.NotionSource', lambda cfg, verbose: source)
    obsidian_cfg.topics_as_tags = True
    cfg.obsidian = obsidian_cfg

    sync_from_notion(cfg, to=('obsidian',), verbose=False)

    path = Path(obsidian_cfg.vault_path) / 'Papers'
    path = path / 'Attention Is All You Need.md'
    frontmatter, _ = ObsidianLibrary._split_note(read(path))
    assert frontmatter['tags'] == ['transformers', '3d-vision']


def test_what_notion_owns_is_declared_in_one_place():
    # The fields a sync may overwrite and an upload may not
    assert AUTHORITATIVE == ('to_read', 'topics')


# ----------------------------------------------------------------------
#  Where the sync writes
# ----------------------------------------------------------------------
def test_notion_cannot_be_synced_to_itself(cfg, capsys):
    with pytest.raises(SystemExit) as e:
        sync_from_notion(cfg, to=(SOURCE,))

    assert e.value.code == 1
    assert 'cannot be synced to itself' in capsys.readouterr().out


def test_notion_is_dropped_from_the_configured_backends(
        cfg, source, obsidian_cfg, monkeypatch):
    monkeypatch.setattr('nora.sync.NotionSource', lambda cfg, verbose: source)
    cfg.obsidian = obsidian_cfg

    # Writing to both is a perfectly normal config, and the sync reads
    # from one of them rather than complaining about it
    cfg.backend = ['notion', 'obsidian']
    counts = sync_from_notion(cfg, verbose=False)

    assert set(counts) == {'obsidian'}


def test_a_config_with_nowhere_to_sync_to_exits(cfg, capsys):
    cfg.backend = 'notion'

    with pytest.raises(SystemExit) as e:
        sync_from_notion(cfg)

    assert e.value.code == 1
    assert 'Nothing to sync to' in capsys.readouterr().out


def test_a_dry_run_of_papers_you_already_have_reports_updates(
        cfg, source, obsidian_cfg, monkeypatch):
    monkeypatch.setattr('nora.sync.NotionSource', lambda cfg, verbose: source)
    cfg.obsidian = obsidian_cfg
    ObsidianSink(obsidian_cfg).write(
        Paper(title='Attention Is All You Need', arxiv_id='1706.03762'))

    counts = sync_from_notion(
        cfg, to=('obsidian',), dry_run=True, verbose=False)

    assert counts == {CREATED: 2, UPDATED: 1}
