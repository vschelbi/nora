import click

from nora.sinks import SINKS
from nora.upload import upload_paper, upload_papers
from nora.utils.config import load_config, configure_user_config
from nora.parsers.zotero import ZoteroLibrary, ZoteroItem


BACKEND_HELP = "Backend to write to. Overrides the `backend` of your config"


@click.group()
def cli():
    """NoRA – Notion & Obsidian Research Assistant"""
    pass


# -------------------------------------------------------------------------
#  nora configure
# -------------------------------------------------------------------------
@cli.command()
def configure():
    """Set up your API keys and Notion/Obsidian/Zotero configuration."""
    configure_user_config()


# -------------------------------------------------------------------------
#  nora url ...
# -------------------------------------------------------------------------
@cli.command("url")
@click.argument("url")
@click.option("--to", type=click.Choice(sorted(SINKS)), help=BACKEND_HELP)
def url_command(url: str, to: str):
    """Process a paper from its URL (e.g., arXiv, DOI)."""
    cfg = load_config()

    # Load from url
    item = ZoteroItem.from_url(url, cfg_venues=cfg.venues)

    # Upload data to NoRA
    if item is not None:
        upload_paper(item.to_paper(), cfg, verbose=cfg.verbose, to=to)


# -------------------------------------------------------------------------
#  nora id ...
# -------------------------------------------------------------------------
@cli.command("id")
@click.argument("id")
@click.option("--to", type=click.Choice(sorted(SINKS)), help=BACKEND_HELP)
def id_command(id: str, to: str):
    """Process a paper from an identifier (DOI, ISBN, PMID, arXiv ID)."""
    cfg = load_config()

    # Load from identifier
    item = ZoteroItem.from_identifier(id, cfg_venues=cfg.venues)

    # Upload data to NoRA
    if item is not None:
        upload_paper(item.to_paper(), cfg, verbose=cfg.verbose, to=to)


# -------------------------------------------------------------------------
#  nora zotero-upload
# -------------------------------------------------------------------------
@cli.command("zotero-upload")
@click.option("--to", type=click.Choice(sorted(SINKS)), help=BACKEND_HELP)
def zotero_upload_command(to: str):
    """Upload your whole Zotero library to NoRA."""
    click.echo("📚 Uploading Zotero to NoRA")

    cfg = load_config()

    # Load the Zotero library
    library = ZoteroLibrary(
        cfg.zotero, cfg_venues=cfg.venues, verbose=cfg.verbose)

    # Upload data to NoRA. The items are converted one at a time: each
    # one queries the Zotero API for its notes and collections, so
    # building them all upfront would front-load hundreds of requests
    upload_papers(
        (item.to_paper() for item in library),
        cfg,
        verbose=cfg.verbose,
        to=to,
        total=len(library))
