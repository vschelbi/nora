from omegaconf import OmegaConf

from nora.paper import Paper
from nora.upload import resolve_backend, upload_paper, upload_papers

from conftest import RecordingSink


def test_resolve_backend_prefers_the_cli_choice(cfg):
    assert resolve_backend(cfg) == 'notion'
    assert resolve_backend(cfg, 'obsidian') == 'obsidian'


def test_resolve_backend_tolerates_a_list(cfg):
    cfg.backend = ['obsidian']
    assert resolve_backend(cfg) == 'obsidian'


def test_resolve_backend_defaults_to_notion():
    # An existing user's config predates the `backend` key
    assert resolve_backend(OmegaConf.create({'verbose': True})) == 'notion'


def test_upload_paper_hands_the_same_object_to_the_sink(cfg, paper):
    sink = RecordingSink()
    upload_paper(paper, cfg, verbose=False, sink=sink)

    assert sink.written[0] is paper


def test_a_failing_paper_does_not_interrupt_the_others(cfg, capsys):
    papers = [Paper(title=f"Paper {i}") for i in (1, 2, 3)]
    sink = RecordingSink(fail_on='Paper 2')

    counts = upload_papers(papers, cfg, sink=sink, total=3)

    # The Notion backend used to exit the process here, losing the rest
    # of a several-hundred-paper upload
    assert [p.title for p in sink.written] == ['Paper 1', 'Paper 3']
    assert counts == {'created': 2, 'failed': 1}
    assert 'simulated backend failure' in capsys.readouterr().out


def test_upload_papers_accepts_a_generator(cfg):
    sink = RecordingSink()
    counts = upload_papers(
        (Paper(title=f"Paper {i}") for i in range(3)), cfg,
        verbose=False, sink=sink, total=3)

    assert counts == {'created': 3}
