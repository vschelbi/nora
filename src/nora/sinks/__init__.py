import sys
from omegaconf import OmegaConf
from typing import List

from nora.sinks.base import (
    Sink, SinkError, WriteResult, CREATED, SKIPPED, UPDATED)
from nora.sinks.notion import NotionLibrary, NotionSink
from nora.sinks.obsidian import ObsidianLibrary, ObsidianSink


__all__ = [
    'SINKS', 'get_sink', 'get_sinks', 'Sink', 'SinkError', 'WriteResult',
    'CREATED', 'SKIPPED', 'UPDATED', 'NotionLibrary', 'NotionSink',
    'ObsidianLibrary', 'ObsidianSink']


# The backends NoRA can write to
SINKS = {
    'notion': NotionSink,
    'obsidian': ObsidianSink}


def get_sink(name: str, cfg: OmegaConf):
    """Instantiate a write backend from its name. The backend-specific
    section of the config is passed to it, so it only ever sees - and
    only ever validates - its own keys.
    """
    if name not in SINKS:
        print(
            f"🛑 Unknown backend '{name}'. Available backends: "
            f"{', '.join(sorted(SINKS))}")
        sys.exit(1)
    return SINKS[name](cfg.get(name))


def get_sinks(names: List[str], cfg: OmegaConf):
    """Instantiate several write backends at once, in the order given.

    All of them are built upfront: a backend whose keys are missing exits
    here, before any paper has been written, rather than halfway through
    an upload that already reached the other backend.
    """
    if not names:
        print(
            "🛑 No backend to write to. Set `backend` in your "
            "~/.nora/user.yaml, or pass `--to`")
        sys.exit(1)
    return [get_sink(name, cfg) for name in names]
