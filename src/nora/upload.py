from omegaconf import OmegaConf
from typing import Iterable, List, Optional

from nora.paper import Paper
from nora.sinks import get_sinks, SinkError, SKIPPED


__all__ = ['resolve_backends', 'upload_paper', 'upload_papers']


# Emoji marking each possible outcome in the logs
STATUS_MARKERS = {
    'created': '✅',
    'updated': '🔄',
    'skipped': 'ℹ️'}


def resolve_backends(cfg: OmegaConf, to=None):
    """Figure out which backends to write to. An explicit CLI choice wins
    over the `backend` of your config file.

    Either of them may name several backends - `backend: [notion,
    obsidian]` in the config, or a repeated `--to notion --to obsidian` -
    in which case every paper is written to all of them, in that order.
    """
    backends = to if to else cfg.get('backend', 'notion')

    # A single backend is a plain string, which is what most configs
    # hold. Commas are tolerated too, as `backend: notion,obsidian` is an
    # easy thing to write by hand
    if isinstance(backends, str):
        backends = backends.split(',')

    # Naming a backend twice would otherwise write every paper to it
    # twice, while `dict.fromkeys` keeps the order that was asked for
    return list(dict.fromkeys(
        str(x).strip().lower() for x in backends if str(x).strip()))


def upload_paper(
        paper: Paper,
        cfg: OmegaConf,
        verbose: bool=True,
        to=None,
        sink=None):
    """Write a single paper to every configured backend. Returns what
    each of them did, keyed by backend name.
    """
    return _write_all(paper, _resolve_sinks(cfg, to, sink), verbose=verbose)


def upload_papers(
        papers: Iterable[Paper],
        cfg: OmegaConf,
        verbose: bool=True,
        to=None,
        sink=None,
        total: int=None):
    """Write many papers to every configured backend. The backends are
    built once for the whole run, and a paper that cannot be written to
    one of them does not interrupt the others.

    Returns the tally of each backend, keyed by backend name.
    """
    sinks = _resolve_sinks(cfg, to, sink)

    counts = {x.name: {} for x in sinks}
    for i, paper in enumerate(papers):
        if verbose:
            position = f"[{i + 1}/{total}]" if total else f"[{i + 1}]"
            print(position, end=' ')

        for name, result in _write_all(paper, sinks, verbose=verbose).items():
            status = result.status if result is not None else 'failed'
            counts[name][status] = counts[name].get(status, 0) + 1

    if verbose:
        for name, tally in counts.items():
            if not tally:
                continue
            summary = ', '.join(f"{v} {k}" for k, v in sorted(tally.items()))
            print(f"📚 {name}: {summary}")

    return counts


def _resolve_sinks(cfg: OmegaConf, to=None, sink=None):
    """The backends to write to. An already-built sink - or list of
    sinks - short-circuits the config, which is what the tests and any
    caller holding a backend of its own use.
    """
    if sink is None:
        return get_sinks(resolve_backends(cfg, to), cfg)
    return list(sink) if isinstance(sink, (list, tuple)) else [sink]


def _write_all(paper: Paper, sinks: List, verbose: bool=True):
    """Write one paper to each backend in turn, and report every outcome.
    """
    if verbose:
        print(f"⬆️ Uploading '{paper.title}'...")

    results = {x.name: _write(paper, x, verbose=verbose) for x in sinks}

    if verbose:
        print('✅ Done')

    return results


def _write(paper: Paper, sink, verbose: bool=True):
    """Write one paper to one backend and report the outcome. A failure
    is reported rather than raised, so that uploading a whole library is
    not lost to a single bad paper, nor the notes one backend accepted
    lost to the other one being misconfigured.
    """
    try:
        result = sink.write(paper)
    except SinkError as e:
        print(f"   ❌ {sink.name}: {e}")
        return None

    if verbose:
        marker = STATUS_MARKERS.get(result.status, '✅')
        detail = f" ({result.message})" if result.message else ''
        print(f"   {marker} {sink.name}: {result.status}{detail}")

    return result
