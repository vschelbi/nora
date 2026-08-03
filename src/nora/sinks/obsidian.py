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

# The link NoRA puts at the end of the managed region. It carries no
# heading, so it is matched out of a region before the sections are split
OPEN_SOURCE_LINK = re.compile(r'^\[Open source\]\((.*)\)[ \t]*$', re.MULTILINE)

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

    def __init__(self, cfg: OmegaConf, authoritative=()):
        sanity_check_config(cfg, ['vault_path'], ['obsidian_vault_path'])

        self.cfg = cfg

        # Logical `paper_keys` names whose value the caller knows better
        # than the note does. A Notion sync owns your reading status and
        # your topics; an upload from the arXiv owns neither, and must
        # leave both alone
        self.authoritative = frozenset(authoritative)
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
        if not self._inside_a_vault():
            print(
                f"⚠️ '{self.vault}' does not look like an Obsidian vault, "
                f"nor a folder inside one (no .obsidian/ here or above). "
                f"Open the vault in Obsidian to use it")

        # One folder per NoRA database
        for key in self._folder_keys():
            self._folder(key).mkdir(parents=True, exist_ok=True)

        # Recognize already-uploaded papers wherever they now live and
        # whatever they are now called
        self._index = self._build_index()

    # ------------------------------------------------------------------
    #  Paths and note names
    # ------------------------------------------------------------------
    def _inside_a_vault(self):
        """Whether `vault_path` is a vault, or sits within one.

        Only the root of a vault carries the `.obsidian` folder, so
        pointing `vault_path` at a subfolder - a `NoRA/` keeping the
        library out of the way of your other notes - has to be recognized
        by looking upwards rather than by the absence of a marker here.
        """
        for folder in (self.vault, *self.vault.parents):
            if (folder / '.obsidian').is_dir():
                return True
        return False

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
        """Map every identity of every already-uploaded paper to its note.

        A note is indexed under its recorded `nora_id` and under the
        identifiers it carries as properties, so that a paper is still
        recognized once a re-upload knows a better identifier for it than
        the one the note was created with.
        """
        index = {}
        folder = self._folder('papers')
        if not folder.is_dir():
            return index

        keys = self.cfg.paper_keys
        for path in sorted(folder.glob('*.md')):
            frontmatter = self._read_frontmatter(path)
            doi = frontmatter.get(keys['doi'])
            arxiv = frontmatter.get(keys['arxiv'])
            ids = [
                frontmatter.get(ID_KEY),
                f"doi:{str(doi).strip().lower()}" if doi else None,
                f"arxiv:{str(arxiv).strip().lower()}" if arxiv else None]
            for nora_id in ids:
                if nora_id and nora_id not in index:
                    index[nora_id] = path

        return index

    def find_note(self, paper: Paper):
        """The note of an already-uploaded paper, or None. Any identity the
        paper is known by is enough to find it.
        """
        for nora_id in _nora_ids(paper):
            path = self._index.get(nora_id)
            if path is not None and path.exists():
                return path
        return None

    def _register(self, paper: Paper, path: Path):
        """Record a note under every identity of its paper.
        """
        for nora_id in _nora_ids(paper):
            self._index[nora_id] = path

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

    def _authoritative_keys(self):
        """The frontmatter keys the caller is authoritative for.
        """
        keys = self.cfg.paper_keys
        owned = {keys[k] for k in self.authoritative if k in keys}

        # Tags are written from the topics, so whoever owns those owns
        # these: clearing a topic in Notion has to clear its tag too
        if 'topics' in self.authoritative:
            owned.add('tags')

        return owned

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

        # Seeded only for a caller that cannot know better. A sync that
        # reads your reading status from Notion is there precisely to
        # write it
        owned = self._authoritative_keys()
        return [k for k in keys if k not in owned]

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

    def paper_body(self, paper: Paper, previous: str=''):
        """Build the NoRA-managed part of a paper note.

        `previous` is the managed region already in the note, if any. It is
        what an upload that knows nothing of the abstract, the notes or the
        source url falls back on, so that a paper re-uploaded from a
        sparser source keeps what a richer one had found - the same reason
        an empty property does not clear a populated one.
        """
        # The link is matched out first, so that it is not swallowed into
        # whichever section happens to precede it
        link = OPEN_SOURCE_LINK.search(previous)
        kept = self._managed_sections(OPEN_SOURCE_LINK.sub('', previous))

        sections = []

        if not self.cfg.abstract_in_frontmatter:
            abstract = paper.abstract or kept.get('Abstract')
            if abstract:
                sections.append(f"## Abstract\n\n{abstract}")

        notes = _notes_to_markdown(paper.notes, paper.notes_format)
        notes = notes or kept.get('Notes')
        if notes:
            sections.append(f"## Notes\n\n{notes}")

        url = paper.url or (link.group(1) if link else None)
        if url:
            sections.append(f"[Open source]({url})")

        if not sections:
            return f"{MANAGED_START}\n{MANAGED_END}\n"

        return (
            f"{MANAGED_START}\n" + '\n\n'.join(sections)
            + f"\n{MANAGED_END}\n")

    @staticmethod
    def _managed_region(body: str):
        """The text NoRA manages inside a note body, without its markers.
        Empty for a note written by hand, which has no managed region.
        """
        start = body.find(MANAGED_START)
        end = body.find(MANAGED_END)
        if start == -1 or end <= start:
            return ''
        return body[start + len(MANAGED_START):end].strip('\n')

    @staticmethod
    def _managed_sections(managed: str):
        """Split a managed region into its `## Heading` sections.
        """
        sections = {}
        heading = None
        lines = []
        for line in managed.splitlines():
            if line.startswith('## '):
                if heading is not None:
                    sections[heading] = '\n'.join(lines).strip('\n')
                heading = line[3:].strip()
                lines = []
            else:
                lines.append(line)
        if heading is not None:
            sections[heading] = '\n'.join(lines).strip('\n')
        return sections

    def write_paper(self, paper: Paper):
        """Create the note of a paper, or refresh an already-existing
        one according to `on_existing`.
        """
        ids = _nora_ids(paper)

        # A paper already uploaded may since have been renamed, or the
        # filename template may have changed, so the identities recorded
        # in the frontmatter are what we search on first
        path = self.find_note(paper)
        if path is not None:
            return self._update_paper(paper, path)

        note_name = self._paper_note_name(paper)
        folder = self._folder('papers')
        path = folder / f"{note_name}.md"

        # Two distinct papers may legitimately share a title
        suffix = 1
        while path.exists():
            if self._read_frontmatter(path).get(ID_KEY) in ids:
                return self._update_paper(paper, path)
            suffix += 1
            path = folder / f"{note_name} ({suffix}).md"

        self._write_atomic(
            path, self._compose(
                self.paper_frontmatter(paper), self.paper_body(paper)))
        self._register(paper, path)

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
        # A field its owner reports as empty really is empty, though:
        # otherwise a topic removed in Notion could never be removed here
        owned = self._authoritative_keys()
        for key, value in list(refreshed.items()):
            if key in owned:
                continue
            if _is_empty(value) and not _is_empty(frontmatter.get(key)):
                refreshed.pop(key)

        frontmatter = {**frontmatter, **refreshed}
        self.create_linked_projects(frontmatter)

        managed = self.paper_body(paper, self._managed_region(body))
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
        self._register(paper, path)

        return WriteResult(UPDATED, ref=str(path))

    def __repr__(self):
        return f"{self.__class__.__name__}({self.vault})"


class ObsidianSink(Sink):

    """Write papers as Markdown notes in an Obsidian vault.
    """

    name = 'obsidian'

    def __init__(self, cfg: OmegaConf, authoritative=()):
        super().__init__(cfg, authoritative=authoritative)
        self.library = ObsidianLibrary(cfg, authoritative=authoritative)

    def has_paper(self, paper: Paper):
        return self.library.find_note(paper) is not None

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
    return _nora_ids(paper)[0]


def _nora_ids(paper: Paper):
    """Every identity a paper may be known by, best first.

    A preprint saved from the arXiv is `arxiv:...`, and gains a DOI once
    it is published - which would make it a different paper, and earn it a
    second note, if only the best identity were ever looked up. So a note
    is indexed under all of these, and matching any one of them is enough
    to recognize a paper you already have.
    """
    ids = []
    if paper.doi:
        ids.append(f"doi:{paper.doi.strip().lower()}")
    if paper.arxiv_id:
        ids.append(f"arxiv:{paper.arxiv_id.strip().lower()}")

    # A title is only ever an identity of last resort: two distinct papers
    # may share one, so it is trusted only when there is nothing better
    if not ids:
        slug = re.sub(r'[^\w]+', '-', (paper.title or '').lower()).strip('-')
        ids.append(f"title:{slug}")

    return ids


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
