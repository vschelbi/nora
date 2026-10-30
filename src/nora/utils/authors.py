import os
import unicodedata
from typing import Dict, Iterable, List

from nora.utils.config import load_yaml


__all__ = ['alias_key', 'load_author_aliases', 'canonical_authors']


def alias_key(name: str):
    """The form an author name is looked up under. Sources disagree on
    case and spacing as much as on the name itself, and macOS stores
    decomposed unicode, so `Håvard` typed in the vault and `Håvard`
    returned by Zotero would otherwise be two different people.
    """
    name = unicodedata.normalize('NFC', str(name))
    return ' '.join(name.split()).casefold()


def load_author_aliases(value) -> Dict[str, str]:
    """Read the `author_aliases` of your config into a lookup from
    `alias_key(variant)` to the canonical name.

    Either form is accepted, and both may be mixed:

        author_aliases:
            J. Gaume: Johan Gaume
            Håvard Boutera Toft: [Håvard B. Toft, Håvard Toft]

    that is `variant: canonical`, or `canonical: [variants]`. A string is
    read as the path of a YAML file holding the same mapping, which keeps
    a long list out of your config.
    """
    if not value:
        return {}

    if isinstance(value, str):
        path = os.path.expanduser(value)
        if not os.path.exists(path):
            print(f"⚠️ No author aliases file at '{path}', ignoring it")
            return {}
        value = load_yaml(path)

    if not hasattr(value, 'items'):
        print("⚠️ `author_aliases` should be a mapping, ignoring it")
        return {}

    aliases = {}
    for key, target in value.items():
        if target is None or isinstance(target, str):
            # `variant: canonical`
            canonical = str(target or '').strip()
            if canonical:
                aliases[alias_key(key)] = canonical
        else:
            # `canonical: [variants]`
            canonical = str(key).strip()
            for variant in target:
                aliases[alias_key(variant)] = canonical

    # A canonical name that is itself a variant of another one is followed
    # through: `a: b` and `b: c` make both into `c`
    aliases = {k: _resolve(v, aliases) for k, v in aliases.items()}

    # And it stands for itself, so that `johan gaume` is written the way
    # you spelled it too
    for canonical in list(aliases.values()):
        aliases.setdefault(alias_key(canonical), canonical)

    return aliases


def _resolve(name: str, aliases: Dict[str, str]):
    """Follow a chain of aliases to its end, stopping at a cycle.
    """
    seen = set()
    while alias_key(name) in aliases and alias_key(name) not in seen:
        seen.add(alias_key(name))
        name = aliases[alias_key(name)]
    return name


def canonical_authors(
        authors: Iterable[str],
        aliases: Dict[str, str]) -> List[str]:
    """The authors of a paper under their canonical names, in their
    original order. An author listed twice once their names are merged -
    under two spellings in one record - is kept once.
    """
    names = [aliases.get(alias_key(x), x) for x in authors or []]
    seen = set()
    kept = []
    for name in names:
        if alias_key(name) not in seen:
            seen.add(alias_key(name))
            kept.append(name)
    return kept
