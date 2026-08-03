import sys
from omegaconf import OmegaConf

from nora.parsers.notion import NotionSource
from nora.sinks import get_sinks, SinkError
from nora.sinks.base import CREATED, UPDATED
from nora.upload import resolve_backends, upload_papers


__all__ = ['SOURCE', 'AUTHORITATIVE', 'sync_from_notion']


# The backend the sync reads from, and so the one it may not write to
SOURCE = 'notion'

# What Notion is the source of truth for. These are the fields you curate
# by hand and no parser can know, so an ordinary upload leaves them alone
# while a sync is there precisely to carry them over. Everything else -
# the title, the authors, the venue - is derived metadata that whichever
# upload ran last is welcome to refresh
AUTHORITATIVE = ('to_read', 'topics', 'projects')


def sync_from_notion(
        cfg: OmegaConf,
        to=None,
        projects=(),
        create_missing: bool=True,
        dry_run: bool=False,
        verbose: bool=True):
    """Carry the reading status and the topics you curate in Notion over
    to your other backends.

    One direction only, on purpose. Making both sides writable means
    reconciling edits, and the way that fails is by quietly losing one of
    them. Notion owns what `AUTHORITATIVE` names, your vault owns the
    notes you write in it and the projects you assign, and nothing has to
    be guessed.
    """
    destinations = _destinations(cfg, to)
    source = NotionSource(cfg.get(SOURCE), verbose=verbose)

    # Every backend is told that Notion knows better for these fields, so
    # that it overwrites what an ordinary upload has to leave alone
    sinks = get_sinks(destinations, cfg, authoritative=AUTHORITATIVE)

    # Read everything before writing anything, so that a backend which
    # goes unreachable halfway through costs a run rather than a partly
    # synced vault
    try:
        papers = list(source)
    except SinkError as e:
        print(f"❌ Notion: {e}")
        print("👉 Nothing was written. Try again once Notion is reachable")
        sys.exit(1)

    if projects:
        papers = _only_projects(papers, projects, verbose)

    if not create_missing:
        papers = [x for x in papers if _already_held(sinks, x)]
        if verbose:
            print(f"⏭️ Refreshing the {len(papers)} already in your backends")

    if dry_run:
        return _report_dry_run(papers, sinks, verbose)

    return upload_papers(
        papers, cfg, verbose=verbose, sink=sinks, total=len(papers))


def _destinations(cfg: OmegaConf, to=None):
    """Where to sync to. An explicit `--to` wins, otherwise everywhere
    else you write. Notion is the source here, so it is never a
    destination - silently when it merely comes from your `backend`, and
    with an error when you asked for it outright.
    """
    if to and SOURCE in to:
        print(
            f"🛑 '{SOURCE}' is what this reads from, so it cannot be synced "
            f"to itself. Drop `--to {SOURCE}`")
        sys.exit(1)

    destinations = [x for x in resolve_backends(cfg, to) if x != SOURCE]
    if not destinations:
        print(
            f"🛑 Nothing to sync to. Set an Obsidian vault in your "
            f"~/.nora/user.yaml, or pass `--to obsidian`")
        sys.exit(1)

    return destinations


def _only_projects(papers, projects, verbose: bool=True):
    """Keep the papers belonging to any of the named Notion projects.
    """
    wanted = {str(x).strip().lower() for x in projects if str(x).strip()}

    # A name matching nothing is nearly always a typo or a quoting slip,
    # and syncing nothing looks exactly like success
    known = {
        str(x).strip().lower(): str(x).strip()
        for paper in papers for x in paper.projects}
    for name in projects:
        if str(name).strip().lower() not in known:
            print(f"⚠️ No paper in Notion belongs to a project called '{name}'")
            if known:
                print(f"👉 Projects found: {', '.join(sorted(known.values()))}")

    kept = [
        x for x in papers
        if any(str(p).strip().lower() in wanted for p in x.projects)]

    if verbose:
        names = ', '.join(str(x) for x in projects)
        print(f"🏗️ {len(kept)} of {len(papers)} papers are in {names}")

    return kept


def _already_held(sinks, paper):
    """Whether any backend already has this paper. A backend that cannot
    tell does not get to claim it is missing.
    """
    answers = [x.has_paper(paper) for x in sinks]
    answers = [x for x in answers if x is not None]
    return any(answers) if answers else True


def _report_dry_run(papers, sinks, verbose: bool=True):
    """Say what the sync would carry over, and write nothing.
    """
    counts = {}
    for i, paper in enumerate(papers):
        status = CREATED if not _already_held(sinks, paper) else UPDATED
        counts[status] = counts.get(status, 0) + 1
        if verbose:
            reading = 'Not started' if paper.to_read else 'Done'
            topics = ', '.join(paper.topics) if paper.topics else 'no topics'
            print(
                f"[{i + 1}/{len(papers)}] {status}: '{paper.title}' "
                f"({reading}; {topics})")

    if verbose:
        summary = ', '.join(f"{v} {k}" for k, v in sorted(counts.items()))
        print(f"📚 {summary or 'nothing to sync'}")
        print("🔍 Dry run: nothing was written")

    return counts
