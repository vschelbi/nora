from omegaconf import OmegaConf

from nora.paper import Paper
from nora.upload import resolve_backends, upload_paper, upload_papers

from conftest import RecordingSink


def test_resolve_backends_prefers_the_cli_choice(cfg):
    assert resolve_backends(cfg) == ['notion']
    assert resolve_backends(cfg, ['obsidian']) == ['obsidian']


def test_resolve_backends_reads_a_list_from_the_config(cfg):
    cfg.backend = ['notion', 'obsidian']
    assert resolve_backends(cfg) == ['notion', 'obsidian']


def test_resolve_backends_keeps_the_requested_order(cfg):
    cfg.backend = ['obsidian', 'notion']
    assert resolve_backends(cfg) == ['obsidian', 'notion']

    # A repeated `--to` is what click hands over
    assert resolve_backends(cfg, ('obsidian', 'notion')) \
        == ['obsidian', 'notion']


def test_resolve_backends_tolerates_a_hand_written_string(cfg):
    cfg.backend = 'notion, obsidian'
    assert resolve_backends(cfg) == ['notion', 'obsidian']


def test_resolve_backends_drops_duplicates(cfg):
    # Writing the same paper twice to one backend is never intended
    assert resolve_backends(cfg, ['notion', 'obsidian', 'notion']) \
        == ['notion', 'obsidian']


def test_resolve_backends_defaults_to_notion():
    # An existing user's config predates the `backend` key
    assert resolve_backends(OmegaConf.create({'verbose': True})) == ['notion']


def test_upload_paper_hands_the_same_object_to_the_sink(cfg, paper):
    sink = RecordingSink()
    upload_paper(paper, cfg, verbose=False, sink=sink)

    assert sink.written[0] is paper


def test_upload_paper_writes_to_every_backend(cfg, paper):
    notion = RecordingSink(name='notion')
    obsidian = RecordingSink(name='obsidian')

    results = upload_paper(paper, cfg, verbose=False, sink=[notion, obsidian])

    assert notion.written == [paper]
    assert obsidian.written == [paper]
    assert set(results) == {'notion', 'obsidian'}


def test_one_failing_backend_does_not_cost_the_other(cfg, capsys):
    papers = [Paper(title=f"Paper {i}") for i in (1, 2)]
    notion = RecordingSink(name='notion', fail_on='Paper 1')
    obsidian = RecordingSink(name='obsidian')

    counts = upload_papers(papers, cfg, sink=[notion, obsidian], total=2)

    # The point of writing to both: whatever one backend refuses is still
    # safely stored in the other
    assert [p.title for p in notion.written] == ['Paper 2']
    assert [p.title for p in obsidian.written] == ['Paper 1', 'Paper 2']
    assert counts == {
        'notion': {'created': 1, 'failed': 1},
        'obsidian': {'created': 2}}
    assert 'simulated backend failure' in capsys.readouterr().out


def test_a_failing_paper_does_not_interrupt_the_others(cfg, capsys):
    papers = [Paper(title=f"Paper {i}") for i in (1, 2, 3)]
    sink = RecordingSink(fail_on='Paper 2')

    counts = upload_papers(papers, cfg, sink=sink, total=3)

    # The Notion backend used to exit the process here, losing the rest
    # of a several-hundred-paper upload
    assert [p.title for p in sink.written] == ['Paper 1', 'Paper 3']
    assert counts == {'recording': {'created': 2, 'failed': 1}}
    assert 'simulated backend failure' in capsys.readouterr().out


def test_upload_papers_accepts_a_generator(cfg):
    sink = RecordingSink()
    counts = upload_papers(
        (Paper(title=f"Paper {i}") for i in range(3)), cfg,
        verbose=False, sink=sink, total=3)

    assert counts == {'recording': {'created': 3}}
