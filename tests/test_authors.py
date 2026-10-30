import unicodedata
from omegaconf import OmegaConf

from nora.utils.authors import (
    alias_key, load_author_aliases, canonical_authors)


def test_no_aliases_is_an_empty_map():
    assert load_author_aliases(None) == {}
    assert load_author_aliases({}) == {}


def test_variant_to_canonical():
    aliases = load_author_aliases({'J. Gaume': 'Johan Gaume'})
    assert canonical_authors(['J. Gaume', 'Ashish Vaswani'], aliases) \
        == ['Johan Gaume', 'Ashish Vaswani']


def test_canonical_to_a_list_of_variants():
    aliases = load_author_aliases({
        'Håvard Boutera Toft': ['Håvard B. Toft', 'Håvard Toft']})
    assert canonical_authors(['Håvard Toft'], aliases) \
        == ['Håvard Boutera Toft']
    assert canonical_authors(['Håvard B. Toft'], aliases) \
        == ['Håvard Boutera Toft']


def test_both_forms_can_be_read_from_an_omegaconf_mapping():
    # What `load_config` hands over, dotted keys included
    cfg = OmegaConf.create({'author_aliases': {
        'J. Gaume': 'Johan Gaume',
        'Elisabeth Hafner-Aeschbacher': ['Elisabeth D. Hafner']}})
    aliases = load_author_aliases(cfg.get('author_aliases'))
    assert canonical_authors(['J. Gaume', 'Elisabeth D. Hafner'], aliases) \
        == ['Johan Gaume', 'Elisabeth Hafner-Aeschbacher']


def test_case_spacing_and_unicode_form_are_ignored():
    aliases = load_author_aliases({'Håvard Toft': 'Håvard Boutera Toft'})
    decomposed = unicodedata.normalize('NFD', 'HÅVARD   toft')
    assert canonical_authors([decomposed], aliases) == ['Håvard Boutera Toft']


def test_the_canonical_name_is_spelled_as_configured():
    aliases = load_author_aliases({'J. Gaume': 'Johan Gaume'})
    assert canonical_authors(['johan gaume'], aliases) == ['Johan Gaume']


def test_a_chain_of_aliases_is_followed_through():
    aliases = load_author_aliases({'J. Gaume': 'J Gaume', 'J Gaume': 'Johan Gaume'})
    assert canonical_authors(['J. Gaume'], aliases) == ['Johan Gaume']


def test_a_cycle_does_not_hang():
    aliases = load_author_aliases({'A': 'B', 'B': 'A'})
    assert len(canonical_authors(['A'], aliases)) == 1


def test_two_spellings_of_one_author_are_kept_once():
    aliases = load_author_aliases({'J. Gaume': 'Johan Gaume'})
    assert canonical_authors(
        ['Johan Gaume', 'Bastian Bergfeld', 'J. Gaume'], aliases) \
        == ['Johan Gaume', 'Bastian Bergfeld']


def test_unknown_authors_are_left_alone():
    assert canonical_authors(['Noam Shazeer'], {}) == ['Noam Shazeer']


def test_aliases_can_live_in_a_yaml_file(tmp_path):
    path = tmp_path / 'authors.yaml'
    path.write_text('J. Gaume: Johan Gaume\n', encoding='utf-8')
    aliases = load_author_aliases(str(path))
    assert aliases[alias_key('J. Gaume')] == 'Johan Gaume'


def test_a_missing_aliases_file_is_warned_about(tmp_path, capsys):
    assert load_author_aliases(str(tmp_path / 'nope.yaml')) == {}
    assert 'No author aliases file' in capsys.readouterr().out
