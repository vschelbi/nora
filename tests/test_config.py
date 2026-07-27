import pytest
from omegaconf import OmegaConf

from nora.sinks import SINKS, get_sink
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


def test_the_shipped_config_declares_both_backends(cfg):
    assert cfg.backend == 'notion'
    assert set(cfg.obsidian.folders) == {
        'papers', 'people', 'affiliations', 'venues', 'topics'}
