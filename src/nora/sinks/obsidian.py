import os
import re
import sys
import yaml
import tempfile
import unicodedata
from pathlib import Path
from markdownify import markdownify
from omegaconf import OmegaConf
from typing import Dict, List, Optional, Tuple

from nora.paper import Paper
from nora.sinks.base import (
    Sink, SinkError, WriteResult, CREATED, SKIPPED, UPDATED)
from nora.utils.keys import sanity_check_config


__all__ = ['ObsidianLibrary', 'ObsidianSink']


# Characters that cannot appear in a note name. The first group is
# forbidden by the filesystems we support, the second is meaningful to
# Obsidian itself and would break the wikilinks pointing at the note
ILLEGAL_CHARACTERS = re.compile(r'[/\\:*?"<>|#^\[\]]')

# Stems Windows refuses to use for a file, whatever the extension
WINDOWS_RESERVED_NAMES = (
    {'CON', 'PRN', 'AUX', 'NUL'}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)})

# The content NoRA writes into a note is delimited by these markers, so
# that re-uploading a paper refreshes them and leaves everything you
# wrote around them untouched. They use the Obsidian comment syntax and
# are therefore invisible in reading view
MANAGED_START = '%% nora:start %%'
MANAGED_END = '%% nora:end %%'

# Frontmatter key holding the identity of a paper. Filenames are allowed
# to change - you may rename a note, or edit `filename_template` - so
# they cannot be used to recognize an already-uploaded paper
ID_KEY = 'nora_id'

# Config section holding the frontmatter keys of each entity folder
ENTITY_KEYS = {
    'people': 'person_keys',
    'venues': 'venue_keys',
    'topics': 'topic_keys',
    'projects': 'project_keys'}

# A wikilink, as written in a frontmatter property. The target may carry
# the folder it lives in, a heading or block reference, and an alias,
# none of which are part of the note name
WIKILINK = re.compile(r'\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]')


class _FrontmatterDumper(yaml.SafeDumper):
    """Dumper writing `None` as an empty value rather than 'null', so
    that empty fields show up as blank editable properties in Obsidian.
    """


_FrontmatterDumper.add_representer(
    type(None),
    lambda dumper, _: dumper.represent_scalar('tag:yaml.org,2002:null', ''))


class _TemplateFields(dict):
    """Filename template fields, tolerating unknown ones rather than
    raising on a typo in the user's config.
    """

    def __missing__(self, key):
        print(
            f"⚠️ Unknown field '{{{key}}}' in your "
            f"`obsidian.filename_template`, ignoring it")
        return ''


class ObsidianLibrary:

    """Holds all the methods for writing into your Obsidian vault.

    Notes are written directly to the filesystem: no plugin and no
    running Obsidian instance are needed, and Obsidian picks up
    externally-created files on its own.
    """

    def __init__(self, cfg: OmegaConf):
        sanity_check_config(cfg, ['vault_path'], ['obsidian_vault_path'])

        self.cfg = cfg
        self.vault = Path(os.path.expanduser(str(cfg.vault_path))).resolve()

        if self.vault.exists() and not self.vault.is_dir():
            print(f"❌ '{self.vault}' is not a directory")
            print("👉 Check the `obsidian.vault_path` in your ~/.nora/user.yaml.")
            sys.exit(1)

        try:
            self.vault.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"❌ Could not create the vault at '{self.vault}': {e}")
            sys.exit(1)

        if not os.access(self.vault, os.W_OK):
            print(f"❌ '{self.vault}' is not writable")
            sys.exit(1)

        # A folder Obsidian has never opened has no .obsidian/, which is
        # perfectly fine for a vault NoRA creates first, so this is only
        # worth a warning
        if not (self.vault / '.obsidian').exists():
            print(
                f"⚠️ '{self.vault}' does not look like an Obsidian vault "
                f"(no .obsidian/ folder). Open it in Obsidian to use it")

        # One folder per NoRA database
        for key in self._folder_keys():
            self._folder(key).mkdir(parents=True, exist_ok=True)

        # Recognize already-uploaded papers wherever they now live and
        # whatever they are now called
        self._index = self._build_index()

    # ------------------------------------------------------------------
    #  Paths and note names
    # ------------------------------------------------------------------
    def _folder_keys(self):
        """The folders NoRA writes into.

        Read off what the code actually uses rather than off `folders`, so
        that a leftover entry in your config - the `affiliations` folder
        NoRA used to create, say - is ignored instead of being recreated
        in your vault on every upload, however often you delete it.
        """
        keys = ['papers'] + list(ENTITY_KEYS)
        if not self.cfg.track_projects:
            keys.remove('projects')
        return keys

    def _folder(self, key: str):
        """Absolute path of one of the NoRA folders in the vault.
        """
        return self.vault / self.cfg.folders[key]

    def _note_name(self, name: str):
        """Turn arbitrary text into a name usable both as a filename and
        as a wikilink target.
        """
        # macOS stores decomposed unicode, so the same title would
        # otherwise yield two different paths across a synced vault
        name = unicodedata.normalize('NFC', str(name))

        name = ILLEGAL_CHARACTERS.sub(' ', name)
        name = ' '.join(name.split())

        # A trailing dot is invalid on Windows, a leading one hides the
        # file, and a template with missing fields leaves separators
        # dangling at the front
        name = name.strip(' .')
        name = re.sub(r'^(?:[-–—,;]+\s*)+', '', name).strip(' .')

        if name.upper() in WINDOWS_RESERVED_NAMES:
            name = f"_{name}"

        max_length = self.cfg.max_filename_length
        if len(name) > max_length:
            name = name[:max_length].rsplit(' ', 1)[0].strip(' .-–—,;')

        return name

    def _paper_note_name(self, paper: Paper):
        """Build a paper's note name from `filename_template`.
        """
        authors = paper.authors or []
        first_author = authors[0].split()[-1] if authors else ''
        if len(authors) > 1:
            all_authors = f"{first_author} et al."
        else:
            all_authors = first_author

        fields = _TemplateFields(
            title=paper.title or '',
            year=paper.year or '',
            venue=paper.venue or '',
            first_author=first_author,
            authors=all_authors,
            arxiv=paper.arxiv_id or '',
            doi=paper.doi or '',
            citekey=_citekey(paper))

        name = self._note_name(
            str(self.cfg.filename_template).format_map(fields))

        # Everything may have been stripped away, for instance for a
        # title made only of illegal characters
        if not name:
            name = self._note_name(
                paper.arxiv_id or paper.doi or '') or 'Untitled'

        return name

    def _link(self, folder_key: str, name: str):
        """Wikilink pointing at an entity note. The full path is used by
        default: a topic and a venue may share a name, in which case a
        short link would be ambiguous. The alias keeps it rendering as
        just the name.
        """
        note_name = self._note_name(name)
        if self.cfg.link_style == 'short':
            return f"[[{note_name}]]"
        folder = self.cfg.folders[folder_key]
        return f"[[{folder}/{note_name}|{note_name}]]"

    # ------------------------------------------------------------------
    #  Reading existing notes
    # ------------------------------------------------------------------
    @staticmethod
    def _read_frontmatter(path: Path):
        """Read only the YAML frontmatter of a note, stopping at its
        closing delimiter rather than reading the whole file.
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                if f.readline().rstrip('\n') != '---':
                    return {}
                lines = []
                for line in f:
                    if line.rstrip('\n') in ('---', '...'):
                        break
                    lines.append(line)
        except (OSError, UnicodeDecodeError):
            return {}

        try:
            return yaml.safe_load(''.join(lines)) or {}
        except yaml.YAMLError:
            return {}

    @staticmethod
    def _split_note(text: str):
        """Split a note into its frontmatter and its body.
        """
        if not text.startswith('---\n'):
            return {}, text

        end = re.search(r'\n(?:---|\.\.\.)[ \t]*(?:\n|$)', text[3:])
        if end is None:
            return {}, text

        raw = text[4:3 + end.start() + 1]
        body = text[3 + end.end():].lstrip('\n')
        try:
            return yaml.safe_load(raw) or {}, body
        except yaml.YAMLError:
            return {}, text

    def _build_index(self):
        """Map the NoRA id of every already-uploaded paper to its note.
        """
        index = {}
        folder = self._folder('papers')
        if not folder.is_dir():
            return index
        for path in sorted(folder.glob('*.md')):
            nora_id = self._read_frontmatter(path).get(ID_KEY)
            if nora_id and nora_id not in index:
                index[nora_id] = path
        return index

    # ------------------------------------------------------------------
    #  Writing
    # ------------------------------------------------------------------
    @staticmethod
    def _dump_frontmatter(data: Dict):
        # `width` keeps PyYAML from wrapping long values, which
        # Obsidian's property parser handles poorly
        return yaml.dump(
            data, Dumper=_FrontmatterDumper, sort_keys=False,
            allow_unicode=True, default_flow_style=False, width=10 ** 9)

    @staticmethod
    def _write_atomic(path: Path, text: str):
        """Write a note in one step, so that an interrupted upload never
        leaves a half-written note behind for Obsidian to index.
        """
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(text)
            os.replace(tmp, str(path))
        except OSError:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def _compose(self, frontmatter: Dict, body: str):
        return f"---\n{self._dump_frontmatter(frontmatter)}---\n\n{body}"

    def create_entity(
            self,
            folder_key: str,
            name: str,
            frontmatter: Dict=None):
        """Create the note of an author, venue, topic or project.
        Existing notes are left alone: you may have written a biography,
        or the plan of a project, in there.
        """
        note_name = self._note_name(name)
        if not note_name:
            return None

        path = self._folder(folder_key) / f"{note_name}.md"
        if path.exists():
            return path

        data = {self.cfg[ENTITY_KEYS[folder_key]]['name']: note_name}
        data.update(frontmatter or {})
        self._write_atomic(path, self._compose(data, ''))

        return path

    def paper_frontmatter(self, paper: Paper):
        """Build the frontmatter properties of a paper note.
        """
        keys = self.cfg.paper_keys
        data = {keys['name']: paper.title}

        data[keys['authors']] = [
            self._link('people', x) for x in paper.authors]

        if paper.venue:
            data[keys['venue']] = self._link('venues', paper.venue)
        else:
            data[keys['venue']] = None

        data[keys['year']] = paper.year
        data[keys['topics']] = [
            self._link('topics', x) for x in paper.topics]

        # Seeded empty, for you to fill in with the projects the paper
        # belongs to. `_seeded_keys` keeps a re-upload from clearing it
        if self.cfg.track_projects:
            data[keys['projects']] = []

        data[keys['url']] = paper.url or None
        data[keys['arxiv']] = paper.arxiv_id
        data[keys['doi']] = paper.doi

        # Mirrors the Notion reading status, so that an Obsidian Bases or
        # Dataview board can group papers the same way
        data[keys['to_read']] = 'Not started' if paper.to_read else 'Done'

        if self.cfg.abstract_in_frontmatter:
            data[keys['abstract']] = paper.abstract

        if self.cfg.topics_as_tags:
            data['tags'] = [_slugify(x) for x in paper.topics]

        data['type'] = 'paper'
        data['source'] = paper.source or None
        data['added'] = paper.date_added
        data[ID_KEY] = _nora_id(paper)

        return data

    def _seeded_keys(self):
        """Frontmatter keys NoRA writes once on a new paper note and never
        touches again, because their content is yours to decide.

        The reading status is one of them: no source NoRA parses knows
        whether you have read a paper, so refreshing it could only ever
        send a paper you are done with back to the top of your queue.
        """
        keys = [self.cfg.paper_keys['to_read']]
        if self.cfg.track_projects:
            keys.append(self.cfg.paper_keys['projects'])
        return keys

    def create_linked_projects(self, frontmatter: Dict):
        """Create the note of every project a paper links to.

        Projects are read back from the note rather than taken from the
        paper metadata: no source NoRA parses knows which of your
        projects a paper serves, so you are the one who wrote them there.
        """
        if not self.cfg.track_projects:
            return

        value = frontmatter.get(self.cfg.paper_keys['projects'])
        for name in _wikilink_names(value):
            self.create_entity('projects', name, {'type': 'project'})

    def paper_body(self, paper: Paper):
        """Build the NoRA-managed part of a paper note.
        """
        sections = []

        if paper.abstract and not self.cfg.abstract_in_frontmatter:
            sections.append(f"## Abstract\n\n{paper.abstract}")

        notes = _notes_to_markdown(paper.notes, paper.notes_format)
        if notes:
            sections.append(f"## Notes\n\n{notes}")

        if paper.url:
            sections.append(f"[Open source]({paper.url})")

        if not sections:
            return f"{MANAGED_START}\n{MANAGED_END}\n"

        return (
            f"{MANAGED_START}\n" + '\n\n'.join(sections)
            + f"\n{MANAGED_END}\n")

    def write_paper(self, paper: Paper):
        """Create the note of a paper, or refresh an already-existing
        one according to `on_existing`.
        """
        nora_id = _nora_id(paper)

        # A paper already uploaded may since have been renamed, or the
        # filename template may have changed, so the identity recorded
        # in the frontmatter is what we search on first
        path = self._index.get(nora_id)
        if path is not None and path.exists():
            return self._update_paper(paper, path)

        note_name = self._paper_note_name(paper)
        folder = self._folder('papers')
        path = folder / f"{note_name}.md"

        # Two distinct papers may legitimately share a title
        suffix = 1
        while path.exists():
            if self._read_frontmatter(path).get(ID_KEY) == nora_id:
                return self._update_paper(paper, path)
            suffix += 1
            path = folder / f"{note_name} ({suffix}).md"

        self._write_atomic(
            path, self._compose(
                self.paper_frontmatter(paper), self.paper_body(paper)))
        self._index[nora_id] = path

        return WriteResult(CREATED, ref=str(path))

    def _update_paper(self, paper: Paper, path: Path):
        """Refresh an existing paper note.
        """
        if self.cfg.on_existing == 'skip':
            return WriteResult(
                SKIPPED, ref=str(path), message="note already exists")

        if self.cfg.on_existing == 'overwrite':
            self._write_atomic(
                path, self._compose(
                    self.paper_frontmatter(paper), self.paper_body(paper)))
            return WriteResult(UPDATED, ref=str(path))

        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        frontmatter, body = self._split_note(text)

        # Properties you added yourself are preserved, the ones NoRA
        # manages are refreshed
        refreshed = self.paper_frontmatter(paper)

        # Except for the ones NoRA merely seeds: the projects you assigned
        # a paper to, and the reading status you set, would otherwise be
        # reset by every re-upload
        for key in self._seeded_keys():
            if key in frontmatter:
                refreshed.pop(key, None)

        # Absence is not deletion. An upload that knows nothing of a field
        # says nothing about it, rather than saying it is empty: the arXiv
        # gives no topics at all, and it should not clear the ones you or
        # a Zotero collection put there. A field that does arrive with a
        # value still refreshes the note
        for key, value in list(refreshed.items()):
            if _is_empty(value) and not _is_empty(frontmatter.get(key)):
                refreshed.pop(key)

        frontmatter = {**frontmatter, **refreshed}
        self.create_linked_projects(frontmatter)

        managed = self.paper_body(paper)
        start = body.find(MANAGED_START)
        end = body.find(MANAGED_END)
        if start != -1 and end > start:
            # Replace only the managed region, so anything you wrote
            # around it survives
            tail = body[end + len(MANAGED_END):].lstrip('\n')
            body = body[:start] + managed + (f"\n{tail}" if tail else '')
        else:
            # A note written by hand, with no managed region to refresh
            body = f"{body.rstrip()}\n\n{managed}" if body.strip() else managed

        self._write_atomic(path, self._compose(frontmatter, body))
        self._index[_nora_id(paper)] = path

        return WriteResult(UPDATED, ref=str(path))

    def __repr__(self):
        return f"{self.__class__.__name__}({self.vault})"


class ObsidianSink(Sink):

    """Write papers as Markdown notes in an Obsidian vault.
    """

    name = 'obsidian'

    def __init__(self, cfg: OmegaConf):
        super().__init__(cfg)
        self.library = ObsidianLibrary(cfg)

    def write(self, paper: Paper):
        try:
            # Authors, venues and topics get a note of their own, so that
            # Obsidian's backlinks and graph reproduce the relations of
            # the Notion databases. Only the name and the type are
            # written: whatever else you keep on an author - a biography,
            # an affiliation, a website - is yours, and NoRA has no
            # source to fill it from anyway
            for author in paper.authors:
                self.library.create_entity(
                    'people', author, {'type': 'person'})
            if paper.venue:
                self.library.create_entity(
                    'venues', paper.venue, {'type': 'venue'})
            for topic in paper.topics:
                self.library.create_entity(
                    'topics', topic, {'type': 'topic'})

            return self.library.write_paper(paper)
        except OSError as e:
            raise SinkError(f"Could not write to the vault: {e}")


def _slugify(text: str):
    """Turn text into something usable as an Obsidian tag, which cannot
    contain spaces.
    """
    text = unicodedata.normalize('NFC', str(text)).strip().lower()
    return re.sub(r'[^\w/-]+', '-', text).strip('-')


def _is_empty(value):
    """Whether a frontmatter value carries no information.

    `not value` will not do: `0` and `False` are answers, not absences,
    and a year or a boolean property of your own must not be treated as
    something NoRA failed to find.
    """
    return value is None or value == '' or value == [] or value == {}


def _wikilink_names(value):
    """Names of the notes a frontmatter property links to.

    Obsidian holds a property as a list or as a single value, so both are
    accepted. Only actual wikilinks count: plain text in the property is
    not a link, so it has no note to point at and NoRA leaves it alone
    rather than guessing a note into existence.
    """
    if value is None:
        return []

    values = value if isinstance(value, (list, tuple)) else [value]

    names = []
    for item in values:
        if not isinstance(item, str):
            continue
        for target in WIKILINK.findall(item):
            # A link written as `Projects/Name` points at `Name`, and a
            # trailing slash would otherwise leave an empty last part
            name = target.strip().rstrip('/').split('/')[-1].strip()
            if name:
                names.append(name)

    # The same project may well be linked twice in one property
    return list(dict.fromkeys(names))


def _citekey(paper: Paper):
    """Build a citation key of the `vaswani2017attention` form.
    """
    authors = paper.authors or []
    last_name = authors[0].split()[-1].lower() if authors else ''
    year = paper.year or ''
    words = re.findall(r'\w+', (paper.title or '').lower())
    words = [w for w in words if len(w) > 3] or words
    first_word = words[0] if words else ''
    return f"{_slugify(last_name)}{year}{first_word}"


def _nora_id(paper: Paper):
    """Stable identity of a paper, recorded in the frontmatter so that
    re-uploading recognizes it however its note has been renamed.
    """
    if paper.doi:
        return f"doi:{paper.doi.strip().lower()}"
    if paper.arxiv_id:
        return f"arxiv:{paper.arxiv_id.strip().lower()}"
    slug = re.sub(r'[^\w]+', '-', (paper.title or '').lower()).strip('-')
    return f"title:{slug}"


def _notes_to_markdown(notes: str, notes_format: str):
    """Render the notes of a paper as Markdown. Zotero child notes come
    as HTML, while the arXiv comment field is plain text.
    """
    if not notes or not notes.strip():
        return ''

    if notes_format != 'html':
        return notes.strip()

    # Unlike the Notion backend, nested lists need no flattening here:
    # Markdown has no depth limit. Underscores and asterisks are left
    # alone rather than backslash-escaped, as notes on papers are full of
    # subscripts such as d_k which would otherwise be unreadable in the
    # Obsidian editor
    return markdownify(
        notes,
        heading_style='ATX',
        bullets='-',
        strong_em_symbol='*',
        escape_underscores=False,
        escape_asterisks=False).strip()
