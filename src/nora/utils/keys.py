import sys
from omegaconf import OmegaConf
from typing import List


__all__ = ['MISSING_VALUES', 'sanity_check_config']


# Values standing for a key the user has not filled in yet. '???' is the
# placeholder shipped in the default config, and an empty string is what
# `nora configure` writes for a prompt you skipped
MISSING_VALUES = (None, '', '???')


def sanity_check_config(
        cfg: OmegaConf,
        keys: List[str],
        expected_keys: List[str]):
    # `OmegaConf.is_missing` is needed here: accessing a '???' value
    # raises MissingMandatoryValue rather than returning it, and that is
    # not an AttributeError, so a getattr default would not catch it
    missing_keys = [
        v for k, v in zip(keys, expected_keys)
        if OmegaConf.is_missing(cfg, k) or cfg.get(k, None) in MISSING_VALUES]
    if len(missing_keys) == 0:
        return
    print(
        "🛑 Missing private keys. Please run `nora configure` to set up "
        "your private keys:\n")
    for v in missing_keys:
        print(f"  - {v}=XXX")
    sys.exit(1)
