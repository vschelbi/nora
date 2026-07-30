import re
import yaml
import pytest
from pathlib import Path
from click.testing import CliRunner
from omegaconf import OmegaConf

from nora.utils import config
from nora.utils.cli import cli

from nora.sinks import SINKS, get_sink, get_sinks
from nora.sinks.base import Sink
from nora.utils.keys import sanity_check_config


@pytest.mark.parametrize('value', ['???', '', None])
def test_missing_keys_give_the_configure_message(value, capsys):
    cfg = OmegaConf.create({'token': value})

    # Accessing a '???' value raises OmegaConf's MissingMandatoryValue,
    # which is not an AttributeError, so this check used to be skipped
    # entirely and the user got a traceback instead
    with pytest.raises(SystemExit) as e:
        sanity_check_config(cfg, ['token'], ['notion_token'])

    assert e.value.code == 1
    assert 'nora configure' in capsys.readouterr().out


def test_a_filled_in_key_passes():
    cfg = OmegaConf.create({'token': 'secret'})
    sanity_check_config(cfg, ['token'], ['notion_token'])


def test_every_backend_is_a_sink():
    assert set(SINKS) == {'notion', 'obsidian'}
    assert all(issubclass(x, Sink) for x in SINKS.values())


def test_an_unknown_backend_lists_the_available_ones(cfg, capsys):
    with pytest.raises(SystemExit) as e:
        get_sink('nope', cfg)

    assert e.value.code == 1
    out = capsys.readouterr().out
    assert 'notion' in out and 'obsidian' in out


def test_no_backend_at_all_is_an_error(cfg, capsys):
    # `backend: []` in a hand-edited config would otherwise silently
    # write the paper nowhere and report success
    with pytest.raises(SystemExit) as e:
        get_sinks([], cfg)

    assert e.value.code == 1
    assert 'No backend' in capsys.readouterr().out


def test_both_backends_are_built_before_anything_is_written(cfg, capsys):
    # The Obsidian vault_path is still '???' here, so building both must
    # fail upfront rather than after Notion has already been written to
    with pytest.raises(SystemExit) as e:
        get_sinks(['obsidian', 'notion'], cfg)

    assert e.value.code == 1
    assert 'nora configure' in capsys.readouterr().out


def test_the_shipped_config_declares_both_backends(cfg):
    assert cfg.backend == 'notion'
    assert set(cfg.obsidian.folders) == {
        'papers', 'people', 'venues', 'topics', 'projects'}


# ----------------------------------------------------------------------
#  nora configure
# ----------------------------------------------------------------------
@pytest.fixture
def configure(monkeypatch, tmp_path):
    """Run `nora configure` against a throwaway config, scripting the
    answers typed at each prompt. Returns the resulting config.
    """
    path = tmp_path / 'user.yaml'
    monkeypatch.setattr(config, 'get_user_config_path', lambda: path)

    def run(answers):
        remaining = iter(answers)
        run.prompts = []

        def fake_input(prompt=''):
            run.prompts.append(prompt)
            return next(remaining)

        monkeypatch.setattr('builtins.input', fake_input)
        config.configure_user_config()
        return OmegaConf.create(config.load_yaml(path))

    run.path = path
    run.prompts = []
    return run


def test_configure_writes_the_answers(configure):
    cfg = configure([
        'notion', 'tok', 'papers', 'people', 'venues', 'topics', '', ''])

    assert cfg.backend == 'notion'
    assert cfg.notion.token == 'tok'
    assert cfg.notion.papers_db_id == 'papers'


def test_configure_keeps_settings_you_edited_by_hand(configure):
    configure([
        'obsidian', '/my/vault', 'zotero-id', 'zotero-token'])

    # The kind of thing you tune in your config and never think about again
    cfg = config.load_yaml(configure.path)
    cfg['obsidian']['link_style'] = 'short'
    cfg['obsidian']['on_existing'] = 'skip'
    cfg['obsidian']['filename_template'] = '{citekey}'
    cfg['venues'] = {'my own venue': 'MINE'}
    with open(configure.path, 'w') as f:
        yaml.dump(cfg, f)

    # Re-running to point at another vault used to reset all of the above
    after = configure(['obsidian', '/other/vault', '', ''])

    assert after.obsidian.vault_path == '/other/vault'
    assert after.obsidian.link_style == 'short'
    assert after.obsidian.on_existing == 'skip'
    assert after.obsidian.filename_template == '{citekey}'
    assert after.venues['my own venue'] == 'MINE'


def test_an_empty_answer_keeps_the_current_value(configure):
    configure([
        'notion', 'tok', 'papers', 'people', 'venues', 'topics',
        'zotero-id', 'zotero-token'])

    # Every prompt skipped: nothing should be blanked
    after = configure(['', '', '', '', '', '', '', ''])

    assert after.backend == 'notion'
    assert after.notion.token == 'tok'
    assert after.notion.topics_db_id == 'topics'
    assert after.zotero.library_id == 'zotero-id'
    assert after.zotero.api_token == 'zotero-token'


def test_configure_offers_the_backend_you_chose_last_time(configure):
    configure([
        'both', 'tok', 'papers', 'people', 'venues', 'topics',
        '/my/vault', '', ''])

    # Enter on the backend prompt keeps both, rather than silently
    # falling back to notion
    after = configure(['', '', '', '', '', '', '', '', ''])

    assert after.backend == ['notion', 'obsidian']
    assert '(both)' in configure.prompts[0]


def test_a_current_value_is_never_echoed_back(configure):
    configure([
        'notion', 'sup3r-s3cret', 'papers', 'people', 'venues', 'topics',
        '', ''])
    configure(['', '', '', '', '', '', '', ''])

    # A terminal is often shared or recorded, so the prompt says a value
    # is there without showing it
    prompts = configure.prompts
    assert not any('sup3r-s3cret' in x for x in prompts)
    assert '[keep current]' in prompts[1]


def test_switching_backend_does_not_lose_the_other_ones_keys(configure):
    configure([
        'notion', 'tok', 'papers', 'people', 'venues', 'topics', '', ''])

    after = configure(['obsidian', '/my/vault', '', ''])

    assert after.backend == 'obsidian'
    assert after.notion.token == 'tok'
    assert after.obsidian.vault_path == '/my/vault'


# ----------------------------------------------------------------------
#  Version
# ----------------------------------------------------------------------
def test_the_two_declared_versions_agree():
    """`pyproject.toml` and `setup.py` both hardcode the version, and
    nothing else makes them match. This is how 2.1.0 came to be declared
    for months without ever being released.
    """
    root = Path(__file__).resolve().parent.parent

    pyproject = re.search(
        r'^version = "([^"]+)"',
        (root / 'pyproject.toml').read_text(),
        re.MULTILINE)
    setup = re.search(
        r'^\s+version="([^"]+)",',
        (root / 'setup.py').read_text(),
        re.MULTILINE)

    assert pyproject and setup, "the version declarations moved"
    assert pyproject.group(1) == setup.group(1)


def test_nora_version_reports_something():
    result = CliRunner().invoke(cli, ['--version'])

    assert result.exit_code == 0
    assert result.output.startswith('nora, version ')

    # 'unknown' is the honest answer from a checkout that was never
    # installed, which is exactly how this suite runs
    assert result.output.split('version ')[1].strip()
