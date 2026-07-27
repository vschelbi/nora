import json
import pytest
from pathlib import Path
from omegaconf import OmegaConf

from nora.paper import Paper
from nora.sinks.base import Sink, SinkError, WriteResult, CREATED
from nora.utils.config import get_config_path, load_yaml


FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture
def cfg():
    """The config NoRA ships with, untouched.
    """
    return OmegaConf.create(load_yaml(get_config_path()))


@pytest.fixture
def obsidian_cfg(cfg, tmp_path):
    """An Obsidian config pointing at an empty vault.
    """
    vault = tmp_path / 'vault'
    (vault / '.obsidian').mkdir(parents=True)
    cfg.obsidian.vault_path = str(vault)
    return cfg.obsidian


@pytest.fixture
def zotero_item_data():
    """A synthetic Zotero API item. Deliberately not a real one: no real
    library id, item key or token belongs in a public repository.
    """
    with open(FIXTURES / 'zotero_item.json') as f:
        return json.load(f)


@pytest.fixture
def paper():
    return Paper(
        title="Attention Is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer"],
        abstract="An abstract.",
        year=2017,
        venue="NeurIPS",
        url="https://arxiv.org/abs/1706.03762",
        topics=["Transformers", "3D vision"],
        notes="<p>A <b>note</b>.</p><ul><li>one<ul><li>deep</li></ul></li></ul>",
        notes_format='html',
        arxiv_id="1706.03762",
        item_type='preprint',
        source='identifier',
        date_added='2026-07-27')


class RecordingSink(Sink):

    """A sink that keeps what it was given, for testing the upload
    orchestration without touching a real backend.
    """

    name = 'recording'

    def __init__(self, fail_on: str=None):
        self.written = []
        self.fail_on = fail_on

    def write(self, paper):
        if paper.title == self.fail_on:
            raise SinkError("simulated backend failure")
        self.written.append(paper)
        return WriteResult(CREATED, ref=paper.title)
