from omegaconf import OmegaConf
from typing import Iterable, List, Optional

from nora.paper import Paper
from nora.sinks import get_sink, SinkError, SKIPPED


__all__ = ['resolve_backend', 'upload_paper', 'upload_papers']


# Emoji marking each possible outcome in the logs
STATUS_MARKERS = {
    'created': '✅',
    'updated': '🔄',
    'skipped': 'ℹ️'}


def resolve_backend(cfg: OmegaConf, to: str=None):
    """Figure out which backend to write to. An explicit CLI choice wins
    over the `backend` of your config file.
    """
    if to:
        return to

    backend = cfg.get('backend', 'notion')

    # Tolerate a hand-edited config using a list
    if not isinstance(backend, str):
        backend = list(backend)[0]

    return backend


def upload_paper(
        paper: Paper,
        cfg: OmegaConf,
        verbose: bool=True,
        to: str=None,
        sink=None):
    """Write a single paper to the configured backend.
    """
    sink = sink if sink is not None else get_sink(resolve_backend(cfg, to), cfg)
    return _write(paper, sink, verbose=verbose)


def upload_papers(
        papers: Iterable[Paper],
        cfg: OmegaConf,
        verbose: bool=True,
        to: str=None,
        sink=None,
        total: int=None):
    """Write many papers to the configured backend. The backend is built
    once for the whole run, and a paper that cannot be written does not
    interrupt the others.
    """
    sink = sink if sink is not None else get_sink(resolve_backend(cfg, to), cfg)

    counts = {}
    for i, paper in enumerate(papers):
        if verbose:
            position = f"[{i + 1}/{total}]" if total else f"[{i + 1}]"
            print(position, end=' ')

        result = _write(paper, sink, verbose=verbose)
        status = result.status if result is not None else 'failed'
        counts[status] = counts.get(status, 0) + 1

    if verbose and counts:
        summary = ', '.join(f"{v} {k}" for k, v in sorted(counts.items()))
        print(f"📚 {summary}")

    return counts


def _write(paper: Paper, sink, verbose: bool=True):
    """Write one paper and report the outcome. A backend failure is
    reported rather than raised, so that uploading a whole library is
    not lost to a single bad paper.
    """
    if verbose:
        print(f"⬆️ Uploading '{paper.title}'...")

    try:
        result = sink.write(paper)
    except SinkError as e:
        print(f"❌ {sink.name}: {e}")
        return None

    if verbose:
        marker = STATUS_MARKERS.get(result.status, '✅')
        detail = f" ({result.message})" if result.message else ''
        print(f"   {marker} {sink.name}: {result.status}{detail}")
        print('✅ Done')

    return result
