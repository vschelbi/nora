import yaml
import pytest
from pathlib import Path

from nora.paper import Paper
from nora.sinks.base import CREATED, SKIPPED, UPDATED
from nora.sinks.obsidian import (
    ObsidianLibrary, ObsidianSink, MANAGED_START, MANAGED_END, ID_KEY)


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


# ----------------------------------------------------------------------
#  Note names
# ----------------------------------------------------------------------
@pytest.mark.parametrize('raw, expected', [
    ('BERT: Pre-training', 'BERT Pre-training'),
    ('a/b\\c*d?e"f<g>h|i', 'a b c d e f g h i'),
    ('Obsidian [[link]] #tag ^caret', 'Obsidian link tag caret'),
    ('  .dots.  ', 'dots'),
    ('CON', '_CON'),
    ('com1', '_com1'),
    ('too    many     spaces', 'too many spaces'),
    ('###', ''),
])
def test_note_name_sanitization(obsidian_cfg, raw, expected):
    assert ObsidianLibrary(obsidian_cfg)._note_name(raw) == expected


def test_note_name_is_truncated(obsidian_cfg):
    name = ObsidianLibrary(obsidian_cfg)._note_name('word ' * 200)
    assert len(name) <= obsidian_cfg.max_filename_length


def test_note_name_normalizes_unicode(obsidian_cfg):
    library = ObsidianLibrary(obsidian_cfg)
    # The same text composed and decomposed must give the same note, or a
    # vault synced between macOS and Linux would grow duplicates
    assert library._note_name('Résumé') == library._note_name('Résumé')


def test_unusable_title_falls_back_to_an_identifier(obsidian_cfg):
    result = ObsidianSink(obsidian_cfg).write(
        Paper(title='###', arxiv_id='2204.07548'))
    assert Path(result.ref).name == '2204.07548.md'


def test_missing_template_fields_do_not_leave_dangling_separators(obsidian_cfg):
    obsidian_cfg.filename_template = '{year} - {venue} - {title}'
    result = ObsidianSink(obsidian_cfg).write(Paper(title='No Year No Venue'))
    assert Path(result.ref).name == 'No Year No Venue.md'


def test_unknown_template_field_is_tolerated(obsidian_cfg):
    obsidian_cfg.filename_template = '{title} {nope}'
    result = ObsidianSink(obsidian_cfg).write(Paper(title='Still Works'))
    assert Path(result.ref).name == 'Still Works.md'


# ----------------------------------------------------------------------
#  Writing
# ----------------------------------------------------------------------
def test_write_creates_a_note_per_entity(obsidian_cfg, paper):
    result = ObsidianSink(obsidian_cfg).write(paper)
    vault = Path(obsidian_cfg.vault_path)

    assert result.status == CREATED
    assert (vault / 'Papers' / 'Attention Is All You Need.md').is_file()
    assert (vault / 'People' / 'Ashish Vaswani.md').is_file()
    assert (vault / 'People' / 'Noam Shazeer.md').is_file()
    assert (vault / 'Venues' / 'NeurIPS.md').is_file()
    assert (vault / 'Topics' / 'Transformers.md').is_file()
    # A topic name with a space cannot be an Obsidian tag, hence the links
    assert (vault / 'Topics' / '3D vision.md').is_file()


def test_an_entity_note_only_holds_its_name_and_type(obsidian_cfg, paper):
    ObsidianSink(obsidian_cfg).write(paper)
    person = Path(obsidian_cfg.vault_path) / 'People' / 'Ashish Vaswani.md'

    frontmatter, _ = ObsidianLibrary._split_note(read(person))

    # NoRA has no source of affiliations or websites, so it used to write
    # these as empty properties that never filled in
    assert frontmatter == {'name': 'Ashish Vaswani', 'type': 'person'}


def test_frontmatter_round_trips(obsidian_cfg, paper):
    paper.title = 'BERT: Pre-training, and "quotes" too'
    result = ObsidianSink(obsidian_cfg).write(paper)

    frontmatter, _ = ObsidianLibrary._split_note(read(result.ref))

    assert frontmatter['title'] == 'BERT: Pre-training, and "quotes" too'
    assert frontmatter['year'] == 2017
    assert frontmatter['authors'] == [
        '[[People/Ashish Vaswani|Ashish Vaswani]]',
        '[[People/Noam Shazeer|Noam Shazeer]]']
    assert frontmatter['reading_status'] == 'Not started'
    assert frontmatter['type'] == 'paper'
    assert frontmatter[ID_KEY] == 'arxiv:1706.03762'


def test_abstract_and_nested_notes_land_in_the_body(obsidian_cfg, paper):
    text = read(ObsidianSink(obsidian_cfg).write(paper).ref)

    assert '## Abstract' in text and 'An abstract.' in text
    assert '## Notes' in text
    # Unlike Notion, nested lists need no flattening
    assert '- one\n  - deep' in text


def test_abstract_can_go_in_the_frontmatter(obsidian_cfg, paper):
    obsidian_cfg.abstract_in_frontmatter = True
    result = ObsidianSink(obsidian_cfg).write(paper)

    frontmatter, body = ObsidianLibrary._split_note(read(result.ref))
    assert frontmatter['abstract'] == 'An abstract.'
    assert '## Abstract' not in body


def test_short_link_style(obsidian_cfg, paper):
    obsidian_cfg.link_style = 'short'
    result = ObsidianSink(obsidian_cfg).write(paper)

    frontmatter, _ = ObsidianLibrary._split_note(read(result.ref))
    assert frontmatter['authors'] == ['[[Ashish Vaswani]]', '[[Noam Shazeer]]']


def test_topics_as_tags(obsidian_cfg, paper):
    obsidian_cfg.topics_as_tags = True
    result = ObsidianSink(obsidian_cfg).write(paper)

    frontmatter, _ = ObsidianLibrary._split_note(read(result.ref))
    # Obsidian tags cannot contain spaces
    assert frontmatter['tags'] == ['transformers', '3d-vision']


# ----------------------------------------------------------------------
#  Re-runs
# ----------------------------------------------------------------------
def test_update_preserves_what_the_user_wrote(obsidian_cfg, paper):
    path = ObsidianSink(obsidian_cfg).write(paper).ref

    # The user adds a property of their own and writes below the managed
    # region
    text = read(path)
    text = text.replace(f"{ID_KEY}:", f"rating: 5\n{ID_KEY}:")
    text += "\n## My own thoughts\n\nDo not delete me.\n"
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)

    paper.abstract = 'A refreshed abstract.'
    result = ObsidianSink(obsidian_cfg).write(paper)
    assert result.status == UPDATED

    text = read(path)
    frontmatter, _ = ObsidianLibrary._split_note(text)

    # This is the regression test for the Notion backend silently
    # discarding notes when re-uploading an existing paper
    assert 'Do not delete me.' in text
    assert frontmatter['rating'] == 5
    assert 'A refreshed abstract.' in text
    assert text.count(MANAGED_START) == 1


def test_update_refreshes_a_note_that_has_no_managed_region(obsidian_cfg, paper):
    vault = Path(obsidian_cfg.vault_path)
    (vault / 'Papers').mkdir(parents=True, exist_ok=True)
    path = vault / 'Papers' / 'Attention Is All You Need.md'
    path.write_text(
        f"---\ntitle: Attention Is All You Need\n{ID_KEY}: arxiv:1706.03762\n"
        f"---\n\nSomething I wrote by hand.\n", encoding='utf-8')

    assert ObsidianSink(obsidian_cfg).write(paper).status == UPDATED

    text = read(path)
    assert 'Something I wrote by hand.' in text
    assert MANAGED_START in text and MANAGED_END in text


def test_skip_leaves_the_note_untouched(obsidian_cfg, paper):
    path = ObsidianSink(obsidian_cfg).write(paper).ref
    before = read(path)

    obsidian_cfg.on_existing = 'skip'
    paper.abstract = 'Never written.'
    result = ObsidianSink(obsidian_cfg).write(paper)

    assert result.status == SKIPPED
    assert read(path) == before


def test_overwrite_replaces_the_whole_note(obsidian_cfg, paper):
    path = ObsidianSink(obsidian_cfg).write(paper).ref
    with open(path, 'a', encoding='utf-8') as f:
        f.write("\nMy own text.\n")

    obsidian_cfg.on_existing = 'overwrite'
    assert ObsidianSink(obsidian_cfg).write(paper).status == UPDATED
    assert 'My own text.' not in read(path)


# ----------------------------------------------------------------------
#  Projects
# ----------------------------------------------------------------------
def assign_projects(path, value):
    """Fill in the `projects` property of a paper note, the way you would
    from the Obsidian properties panel.
    """
    frontmatter, body = ObsidianLibrary._split_note(read(path))
    frontmatter['projects'] = value
    with open(path, 'w', encoding='utf-8') as f:
        f.write(
            f"---\n{ObsidianLibrary._dump_frontmatter(frontmatter)}---\n\n"
            f"{body}")


def test_a_new_paper_gets_an_empty_projects_property(obsidian_cfg, paper):
    result = ObsidianSink(obsidian_cfg).write(paper)

    frontmatter, _ = ObsidianLibrary._split_note(read(result.ref))

    # There for you to fill in from the properties panel, since no source
    # NoRA reads from knows which project a paper serves
    assert frontmatter['projects'] == []
    assert (Path(obsidian_cfg.vault_path) / 'Projects').is_dir()


def test_assigned_projects_survive_a_re_upload(obsidian_cfg, paper):
    path = ObsidianSink(obsidian_cfg).write(paper).ref
    assign_projects(path, ['[[Projects/Thesis chapter 3|Thesis chapter 3]]'])

    paper.abstract = 'A refreshed abstract.'
    assert ObsidianSink(obsidian_cfg).write(paper).status == UPDATED

    frontmatter, _ = ObsidianLibrary._split_note(read(path))

    # The seeded empty value must not clobber what you assigned
    assert frontmatter['projects'] == [
        '[[Projects/Thesis chapter 3|Thesis chapter 3]]']
    assert 'A refreshed abstract.' in read(path)


def test_a_linked_project_gets_a_note(obsidian_cfg, paper):
    path = ObsidianSink(obsidian_cfg).write(paper).ref
    assign_projects(path, ['[[Projects/Thesis chapter 3|Thesis chapter 3]]'])

    ObsidianSink(obsidian_cfg).write(paper)
    note = Path(obsidian_cfg.vault_path) / 'Projects' / 'Thesis chapter 3.md'

    assert note.is_file()
    frontmatter, _ = ObsidianLibrary._split_note(read(note))
    assert frontmatter == {'name': 'Thesis chapter 3', 'type': 'project'}


def test_a_project_note_you_wrote_is_never_overwritten(obsidian_cfg, paper):
    vault = Path(obsidian_cfg.vault_path)
    path = ObsidianSink(obsidian_cfg).write(paper).ref
    note = vault / 'Projects' / 'Thesis.md'
    note.write_text("---\nname: Thesis\n---\n\nMy plan.\n", encoding='utf-8')

    assign_projects(path, ['[[Thesis]]'])
    ObsidianSink(obsidian_cfg).write(paper)

    assert 'My plan.' in read(note)


@pytest.mark.parametrize('value, expected', [
    (['[[Projects/Thesis|Thesis]]'], ['Thesis']),
    (['[[Thesis]]'], ['Thesis']),
    ('[[Projects/Thesis]]', ['Thesis']),
    (['[[Projects/Thesis#Goals|Goals]]'], ['Thesis']),
    (['[[A]]', '[[B]]'], ['A', 'B']),
    (['[[A]]', '[[Projects/A|A]]'], ['A']),
    # Plain text is not a link, so there is no note to point at
    (['Thesis'], []),
    ([], []),
    (None, []),
])
def test_project_links_are_parsed(obsidian_cfg, paper, value, expected):
    path = ObsidianSink(obsidian_cfg).write(paper).ref
    assign_projects(path, value)

    ObsidianSink(obsidian_cfg).write(paper)
    folder = Path(obsidian_cfg.vault_path) / 'Projects'

    assert sorted(p.stem for p in folder.glob('*.md')) == sorted(expected)


def test_projects_can_be_turned_off(obsidian_cfg, paper):
    obsidian_cfg.track_projects = False
    result = ObsidianSink(obsidian_cfg).write(paper)

    frontmatter, _ = ObsidianLibrary._split_note(read(result.ref))

    assert 'projects' not in frontmatter
    assert not (Path(obsidian_cfg.vault_path) / 'Projects').exists()


def test_overwrite_clears_assigned_projects(obsidian_cfg, paper):
    path = ObsidianSink(obsidian_cfg).write(paper).ref
    assign_projects(path, ['[[Projects/Thesis|Thesis]]'])

    # 'overwrite' replaces the note entirely, projects included: that is
    # its documented contract, unlike 'update'
    obsidian_cfg.on_existing = 'overwrite'
    ObsidianSink(obsidian_cfg).write(paper)

    frontmatter, _ = ObsidianLibrary._split_note(read(path))
    assert frontmatter['projects'] == []


def test_a_renamed_note_is_found_by_its_identity(obsidian_cfg, paper):
    original = Path(ObsidianSink(obsidian_cfg).write(paper).ref)
    renamed = original.with_name('I renamed this note.md')
    original.rename(renamed)

    result = ObsidianSink(obsidian_cfg).write(paper)

    assert result.status == UPDATED
    assert Path(result.ref) == renamed
    # No duplicate was created under the templated name
    assert not original.exists()


def test_changing_the_filename_template_does_not_duplicate(obsidian_cfg, paper):
    ObsidianSink(obsidian_cfg).write(paper)

    obsidian_cfg.filename_template = '{year} - {title}'
    result = ObsidianSink(obsidian_cfg).write(paper)

    assert result.status == UPDATED
    papers = list((Path(obsidian_cfg.vault_path) / 'Papers').glob('*.md'))
    assert len(papers) == 1


def test_two_distinct_papers_may_share_a_title(obsidian_cfg, paper):
    first = ObsidianSink(obsidian_cfg).write(paper)
    other = Paper(title=paper.title, doi='10.1000/completely-different')
    second = ObsidianSink(obsidian_cfg).write(other)

    assert second.status == CREATED
    assert first.ref != second.ref
    assert Path(second.ref).name == 'Attention Is All You Need (2).md'


def test_entity_notes_are_never_overwritten(obsidian_cfg, paper):
    ObsidianSink(obsidian_cfg).write(paper)
    person = Path(obsidian_cfg.vault_path) / 'People' / 'Ashish Vaswani.md'

    with open(person, 'a', encoding='utf-8') as f:
        f.write("\nA biography I wrote.\n")

    ObsidianSink(obsidian_cfg).write(paper)
    assert 'A biography I wrote.' in read(person)


# ----------------------------------------------------------------------
#  Vault validation
# ----------------------------------------------------------------------
def test_a_missing_vault_is_created(cfg, tmp_path):
    cfg.obsidian.vault_path = str(tmp_path / 'brand' / 'new' / 'vault')
    library = ObsidianLibrary(cfg.obsidian)

    assert library.vault.is_dir()
    for folder in cfg.obsidian.folders.values():
        assert (library.vault / folder).is_dir()


def test_a_leftover_folder_in_the_config_is_ignored(cfg, tmp_path, paper):
    vault = tmp_path / 'vault'
    (vault / '.obsidian').mkdir(parents=True)
    cfg.obsidian.vault_path = str(vault)

    # What an older `nora configure` left in a long-time user's config
    cfg.obsidian.folders.affiliations = 'Affiliations'

    ObsidianSink(cfg.obsidian).write(paper)
    assert not (vault / 'Affiliations').exists()

    # And deleting it stays deleted, rather than coming back on every
    # upload
    (vault / 'Affiliations').mkdir()
    (vault / 'Affiliations').rmdir()
    ObsidianSink(cfg.obsidian).write(paper)
    assert not (vault / 'Affiliations').exists()


def test_a_vault_path_pointing_at_a_file_exits(cfg, tmp_path):
    target = tmp_path / 'not-a-directory.md'
    target.write_text('hello', encoding='utf-8')
    cfg.obsidian.vault_path = str(target)

    with pytest.raises(SystemExit):
        ObsidianLibrary(cfg.obsidian)


def test_a_missing_vault_path_gives_the_configure_message(cfg):
    with pytest.raises(SystemExit):
        ObsidianLibrary(cfg.obsidian)
