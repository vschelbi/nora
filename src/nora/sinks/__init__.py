import sys
from omegaconf import OmegaConf

from nora.sinks.base import (
    Sink, SinkError, WriteResult, CREATED, SKIPPED, UPDATED)
from nora.sinks.notion import NotionLibrary, NotionSink
from nora.sinks.obsidian import ObsidianLibrary, ObsidianSink


__all__ = [
    'SINKS', 'get_sink', 'Sink', 'SinkError', 'WriteResult', 'CREATED',
    'SKIPPED', 'UPDATED', 'NotionLibrary', 'NotionSink', 'ObsidianLibrary',
    'ObsidianSink']


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
