<div align="center">

# NoRA - Notion/Obsidian Research Assistant

[![python](https://img.shields.io/badge/-Python-blue?logo=python&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![node.js](https://img.shields.io/badge/Node.js-43853D?logo=node.js&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![license](https://img.shields.io/badge/License-MIT-green.svg?labelColor=gray)](https://github.com/ashleve/lightning-hydra-template#license)

This repo is forked from [drprojects/nora](https://github.com/drprojects/nora).

Keep track of the papers you read 📜, their authors 👤, your notes 📝, and more 🔥 —
in **Notion** or in **Obsidian**

**_If you ❤️ or simply use this project, don't forget to give the repository a ⭐,
it means a lot to us !_**
</div>

<br>

## 📌  Introduction

This project was built as an alternative to reference management software such as 
Zotero and Mendeley, on top of the note-taking app you already use.

It is composed of the **NoRA Notion template** for you to build on top of, as 
well as **NoRA-Tools** to programmatically:
- 🔥 upload papers to your NoRA library as easily as with 
[Zotero Connector](https://www.zotero.org/download/connectors) from a simple URL or an identifier
- 🔥 move all your already-existing Zotero library to NoRA

NoRA can write to two **backends**, which you pick with the `backend` key of your
config or with `--to` on any command:

| Backend | What you get |
|---|---|
| [`notion`](https://www.notion.so) | Five interconnected Notion databases, as in the NoRA template |
| [`obsidian`](https://obsidian.md) | Markdown notes written straight into your vault, with `[[wikilinks]]` between papers, authors, venues and topics |

Both produce the same metadata, and you can write to **both at once** — see 
[choosing a backend](#choosing-where-nora-writes).

### 🧪  NoRA template

The NoRA Notion template provides you with a structure of interconnected databases to 
keep track of your research papers and notes.
More specifically, the template contains the following databases:
- `🏗️ Projects`
- `📜 Papers`
- `👤 People`
- `🏢 Affiliations`
- `🤹 Conferences & journals`
- `🧲 Key topics`

The inner workings of the template are quite straightforward, the best way to 
get familiar with it is probably to play with it 😉 !

NoRA-Tools uploads to four of them — `📜 Papers`, `👤 People`, 
`🤹 Conferences & journals` and `🧲 Key topics`. `🏗️ Projects` is yours to assign by 
hand, and `🏢 Affiliations` is yours entirely — see *What NoRA does not fill in* 
under [advanced usage](#advanced-usage).

### 🛠  NoRA-Tools

The NoRA-Tools provide functionalities to programmatically upload data to your 
NoRA template. The main functionalities are:

- uploading a paper and associated metadata to NoRA from a URL or 
from an identifier (DOI, ISBN, PMID, arXiv ID), exactly like with 
[Zotero Connector](https://www.zotero.org/download/connectors)
- uploading your whole Zotero library to NoRA

<br>

## 🧱  Installation

### Requirements
- [Python](https://www.python.org/downloads) ≥ 3.9  
- [pip](https://pip.pypa.io/en/stable/installation)
- [Node.js](https://nodejs.org/en/download) ≥ 18 and ≤ 20  
- a [Notion](https://www.notion.com) account with API credentials, an 
[Obsidian](https://obsidian.md) vault, or both
- (optional) [Zotero](https://www.zotero.org) account with API credentials

> **Note**: We have experienced issues with too-recent `node.js` 
> versions such as `node 23` so we recommend making sure you use 
> `node 20` for now. You can check your version by running `node -v`.

> **Note**: NoRA installs the [Zotero translation server](https://github.com/zotero/translation-server)
> at a pinned revision (`TRANSLATION_SERVER_REF` in `setup.py`), rather 
> than at its latest revision. Upstream moved to `jsdom 29` in April 2026,
> which requires `node >= 20.19` and otherwise fails to start with an 
> `ERR_REQUIRE_ESM` error. If you are on `node >= 20.19` and want more 
> recent translators, you can bump `TRANSLATION_SERVER_REF` and reinstall.

> **Note**: Follow the Notion and Obsidian sections below for the backend, or 
> backends, you intend to use, and skip the other. Setting up both is what 
> [writing to Notion and Obsidian at once](#writing-to-notion-and-obsidian-at-once)
> needs.

### Installing the template in Notion

Simply duplicate the [NoRA template](https://silent-switch-780.notion.site/Template-research-library-286d3393a7e845c6a689a5c693790987) to your personal Notion account.

> **Note**: You can freely modify or extend the NoRA template. However, keep in 
> mind that if you want to use NoRA-Tools after modifying some sensitive page 
> fields, you may need to adjust your 
> [Notion configuration](#advanced-usage) accordingly.

### Getting your Notion API keys

Next, you will need to prepare some private keys needed to upload data 
to your NoRA.
To this end, do the following:
- [Create an integration](https://developers.notion.com/docs/create-a-notion-integration) for your NoRA workspace
- [Recover your **API secret token**](https://developers.notion.com/docs/create-a-notion-integration#get-your-api-secret)
- For each database NoRA writes to (i.e. Papers, People, Venues, Topics):
  - [Give your integration permission to access this database](https://developers.notion.com/docs/create-a-notion-integration#give-your-integration-page-permissions)
  - Recover your **database ID**. For this, open the database page **in a browser**. The
database ID is a 32-alphanumeric-character that can be recovered from the URL of the page:
`https://www.notion.so/this_is_your_32_character_database_id?v=you_can_ignore_the_rest`

Once you have recovered your **API secret token** and the **database IDs**, 
you should have something like this:

````yaml
notion:
    token: your_api_secret_token
    papers_db_id: your_papers_database_id
    people_db_id: your_people_database_id
    venues_db_id: your_venues_database_id
    topics_db_id: your_topics_database_id
````
Keep these safe somewhere, we will need these in a bit!

### Setting up your Obsidian vault

Nothing to install: NoRA writes Markdown files straight into your vault, so no 
community plugin is needed and Obsidian does not even have to be running. All 
you need is the path to your vault:

````yaml
obsidian:
    vault_path: /path/to/your/vault
````

NoRA creates one folder per database it writes to — `Papers`, `People`, `Venues`, 
`Topics` and `Projects` — and links them together with `[[wikilinks]]`, so 
Obsidian's **backlinks** and **graph view** give you the same relations as the 
Notion databases: open an author's note and it lists every one of their papers.

A paper note looks like this:

````markdown
---
title: Attention Is All You Need
authors:
- '[[People/Ashish Vaswani|Ashish Vaswani]]'
- '[[People/Noam Shazeer|Noam Shazeer]]'
venue: '[[Venues/NeurIPS|NeurIPS]]'
year: 2017
topics:
- '[[Topics/Transformers|Transformers]]'
projects: []
url: https://arxiv.org/abs/1706.03762
arxiv: '1706.03762'
doi:
reading_status: Not started
type: paper
nora_id: arxiv:1706.03762
---

%% nora:start %%
## Abstract

The dominant sequence transduction models are based on ...

## Notes

- Multi-head attention lets the model attend to several subspaces

[Open source](https://arxiv.org/abs/1706.03762)
%% nora:end %%
````

Five things worth knowing:

- **Links are only written on the paper.** An author, venue or topic note carries 
no list of papers, unlike its Notion counterpart. A wikilink needs recording only 
once, and Obsidian derives the reverse direction itself: open `People/Ashish 
Vaswani`, and the **backlinks** pane at the bottom lists every paper linking to 
them, the **graph view** draws the edges, and `[[Ashish Vaswani]]` autocompletes 
anywhere. So an author note stays as small as this, and yours to fill in:

  ````markdown
  ---
  name: Ashish Vaswani
  type: person
  ---
  ````

  It also means NoRA never rewrites an entity note it has already created — your 
biography of an author, or your reading plan for a venue, is safe there. If you 
would rather have the papers as a real, sortable property, a 
[Bases](https://help.obsidian.md/bases) or Dataview query on the author note 
computes it from the paper side, and stays correct when a paper is renamed or 
deleted:

  ````
  ```dataview
  LIST FROM [[]] AND "Papers"
  ```
  ````

- **Your writing is safe.** Everything NoRA generates sits between the 
`%% nora:start %%` and `%% nora:end %%` markers, which are Obsidian comments and 
therefore invisible in reading view. Re-uploading a paper refreshes that block 
and the properties it manages, and leaves anything you wrote around them — and 
any property you added yourself — untouched.
- **Renaming notes is fine.** Papers are recognized by the `nora_id` property 
rather than by their filename, so you can rename a note, or change 
`filename_template`, without NoRA creating a duplicate.
- **Projects and the reading status are yours.** These two properties NoRA writes 
once and never touches again, because no source it reads from knows which of your 
projects a paper serves or whether you have read it. Re-uploading a paper you have 
marked `Done` leaves it `Done`. See 
[assigning papers to projects](#assigning-papers-to-projects) below.
- **An upload that knows less never erases more.** Refreshing a note only sets the 
properties the upload actually carries a value for. The arXiv reports no topics, so 
re-uploading a paper from there leaves the topics you or a Zotero collection put on 
it alone, rather than emptying them — and the same goes for a venue or a DOI that 
one source knows and another does not.

Since the frontmatter is plain properties, you can rebuild the Notion table view 
with [Bases](https://help.obsidian.md/bases) or Dataview:

````
```dataview
TABLE year AS Year, venue AS Venue, authors AS Authors, reading_status AS Status
FROM "Papers"
WHERE type = "paper"
SORT year DESC
```
````

### Assigning papers to projects

The `🏗️ Projects` database of the Notion template has an Obsidian equivalent: a 
`Projects` folder, and a `projects` property on every paper note.

Which project a paper serves is something only you know — Zotero and the arXiv 
certainly do not — so NoRA cannot fill this in the way it fills authors or venues. 
What it does instead is get out of your way:

- every new paper note gets an empty `projects` property, so it is already in the 
properties panel waiting to be filled
- whatever you put there **survives every re-upload**. This is the one property 
NoRA seeds and then never touches again
- each project you link to gets a note of its own in `Projects/`, created on the 
next upload of any paper pointing at it

Assign a paper by linking projects from its properties panel, or by editing the 
frontmatter directly:

````yaml
projects:
- '[[Projects/Thesis chapter 3|Thesis chapter 3]]'
- '[[Reading group]]'
````

Both link styles work, aliases and headings are understood, and the note name is 
taken from the last path segment — so the two lines above produce 
`Projects/Thesis chapter 3.md` and `Projects/Reading group.md`. Plain text is not a 
link and creates nothing, so `projects: [Thesis]` leaves your vault alone.

A project note holds only its name and type, like every other entity note, which 
means Obsidian's **backlinks** pane on it is your reading list for that project:

````markdown
---
name: Thesis chapter 3
type: project
---
````

And as with authors, a query turns that into a real list you can put in the note 
and sort:

````
```dataview
TABLE year AS Year, venue AS Venue, reading_status AS Status
FROM [[]] AND "Papers"
SORT year DESC
```
````

Two things to keep in mind:

- A project note is never overwritten once it exists, so it is a good place for the 
plan, the deadline or the draft that goes with the project.
- `on_existing: 'overwrite'` does what it says and replaces the whole note, 
projects included. Use the default `'update'` if you assign projects by hand — 
which is the whole point of the property.

Set `track_projects: False` in the `obsidian` section of your `~/.nora/user.yaml` 
if you would rather not have any of this: no property on paper notes, and no 
`Projects` folder.

> **Note**: this is Obsidian-only. In Notion, the `🏗️ Projects` database and its 
> relation already exist in the template, so the property is there to fill in 
> without NoRA having to seed anything — and NoRA does not write to it either.

### Getting your Zotero API keys (optional)

If you intend to move your whole Zotero library to Notion, you will need to
get some private keys to download your library.
To this end, you will need to:
- Get your Zotero **library ID** by checking the UserID in your [profile settings](https://www.zotero.org/settings/keys)
- Create a Zotero **API key** in your [profile settings](https://www.zotero.org/settings/keys)

You should then have something like this:

````yaml
zotero:
    library_id: your_library_id
    api_token: your_api_key
````

Keep these safe somewhere, we will need these in a bit!

### Installing NoRA-Tools on your machine
Open a terminal and run
```bash
pip install git+https://github.com/drprojects/nora.git
```

<details>
<summary><b>👩‍💻 NoRA from source for developers</b></summary>

If you want to extend NoRA-Tools to your need, you can install from source:

```bash
# Get the source code
git clone https://github.com/drprojects/nora

# Install the python dependencies. This also clones the pinned revision
# of the translation server into src/nora/translation_server and
# installs its node.js dependencies for you
cd nora
pip install -e .
```
</details>

then configure you API keys
```bash
nora configure
```
this will prompt you to pass your secret keys, which will be saved in 
`~/.nora/user.yaml`.

You can re-run it whenever you like: it is an update rather than a reset. Every 
prompt offers to keep the value it already has — press Enter to leave it alone — 
and any setting you edited by hand is preserved. So pointing NoRA at a new vault 
takes one answer and costs you neither your Notion token nor your customized 
`venues`, `link_style` or `filename_template`.

<details>
<summary><b>
⚠️ Are you using a `.netrc` file with a `default` configuration?</b></summary>

If you are using a `~/.netrc` file to keep track of your passwords locally, 
and have declared a `default` account among your configurations, the `requests`
library will crash when trying to connect to Notion. Please remove your 
`default` account and all should be fine 😉

</details>

### Uninstalling NoRA-Tools from your machine
Open a terminal and run
```bash
pip uninstall nora
```

<br>

## ⚡  Using NoRA-Tools

### Uploading a paper to NoRA

NoRA-Tools mimics the behavior of the 
[Zotero Connector](https://www.zotero.org/download/connectors), which 
has two mechanisms for uploading a paper.

From a URL:

```bash
nora url https://arxiv.org/abs/2204.07548
```

From an identifier (DOI, ISBN, PMID, arXiv ID):

```bash
nora id 2204.07548
```

### Uploading your entire Zotero library to NoRA

```bash
nora zotero-upload
```

### Choosing where NoRA writes

`nora configure` asks where you want your papers and only prompts for the keys of 
the backends you name — offering, on a re-run, the answer you gave last time. The 
keys of a backend you are *not* configuring stay in your config, so switching away 
from Notion and back later does not mean hunting down your database ids again. You 
can also change your mind by editing your `~/.nora/user.yaml` directly:

````yaml
backend: obsidian   # or 'notion'
````

Any command also takes a `--to` flag, which overrides the config for that run — 
handy to try Obsidian out without committing to it:

```bash
nora url https://arxiv.org/abs/2204.07548 --to obsidian
nora id 2204.07548 --to notion
nora zotero-upload --to obsidian
```

### Writing to Notion and Obsidian at once

Answer `both` when `nora configure` asks, and every paper is written to your 
Notion databases **and** your vault in one pass — one lookup of the metadata, two 
destinations. In your `~/.nora/user.yaml` this is simply a list, so you can also 
switch to it later by hand:

````yaml
backend: [notion, obsidian]
````

Both the `notion` and the `obsidian` sections then have to be filled in. NoRA 
connects to every backend before writing anything, so a missing Notion token or 
vault path stops the run upfront instead of halfway through.

Repeating `--to` does the same for a single run, and overrides the config either 
way — useful to backfill a vault from a Notion-only setup:

```bash
nora url https://arxiv.org/abs/2204.07548 --to notion --to obsidian
nora zotero-upload --to notion --to obsidian
```

Each paper reports what every backend did with it, and the run ends with one 
tally per backend:

```
[1/2] ⬆️ Uploading 'Attention Is All You Need'...
   ✅ notion: created
   🔄 obsidian: updated
✅ Done
[2/2] ⬆️ Uploading 'Segment Any Point Cloud'...
   ❌ notion: rate-limited by the Notion API
   ✅ obsidian: created
✅ Done
📚 notion: 1 created, 1 failed
📚 obsidian: 1 created, 1 updated
```

As the second paper shows, the backends are independent: one of them failing — 
an expired Notion token, a vault on an unmounted drive — costs you neither the 
other backend nor the rest of the upload. Re-running the same command later 
picks up what was missed, since both backends recognize the papers they already 
hold rather than duplicating them.

### Advanced usage

You can further customize the behavior of NoRA-Tools by manually editing
your personal config file located at `~/.nora/user.yaml`.

<details>
<summary><b>Customizing your Obsidian vault</b></summary>

The `obsidian` section of your `~/.nora/user.yaml` controls how notes are 
written:

````yaml
obsidian:
    vault_path: /path/to/your/vault

    # Subfolders of the vault, one per NoRA database. Created if missing.
    # Only these are created: an entry left over from an older version of
    # NoRA is ignored rather than recreated in your vault
    folders:
        papers: 'Papers'
        people: 'People'
        venues: 'Venues'
        topics: 'Topics'
        projects: 'Projects'

    # Name given to the note of a paper. Available fields: {title},
    # {year}, {venue}, {first_author}, {authors}, {arxiv}, {doi}, {citekey}
    filename_template: '{title}'
    max_filename_length: 180

    # What to do when the note of a paper already exists. 'update'
    # refreshes its properties and the NoRA-managed section and preserves
    # whatever you wrote around them, including your reading status, your
    # projects and any property the upload has no value for. 'skip' leaves
    # the note untouched, 'overwrite' replaces it entirely
    on_existing: 'update'

    # How authors, venues and topics are linked from a paper. 'path'
    # links stay unambiguous even when a topic and a venue share a name,
    # 'short' ones are terser
    link_style: 'path'

    # Long abstracts clutter the Obsidian properties panel, so they are
    # written in the body of the note by default
    abstract_in_frontmatter: False

    # Also record the key topics as Obsidian tags, alongside the links
    topics_as_tags: False

    # Seed a `projects` property on new paper notes, and create a note
    # for every project you link to from one. False leaves projects out
    track_projects: True
````

The frontmatter keys themselves are configurable too, under 
`obsidian.paper_keys`, `obsidian.person_keys`, and so on — same idea as the 
Notion field names below.

</details>

<details>
<summary><b>Modifying database names in NoRA️</b></summary>

By default, NoRA-Tools expect the attribute fields (e.g. column names in Notion)
of your papers, people, etc. to have specific values. If you want to adjust 
those, you can do so by overwriting the keys in the `notion` section of your 
personal config file `~/.nora/user.yaml`:

````yaml
# If you happen to modify your field names in Notion, update the
# following database-specific keys
person_keys:
    name: 'Name'
    papers: '📜 Papers'

paper_keys:
    name: 'Name'
    authors: '👤 Authors'
    abstract:  'Abstract'
    topics: '🧲 Key topics'
    url: 'URL'
    to_read: 'Reading status'
    year: 'Year'
    venue:  '🤹 Venue'

venue_keys:
    name: 'Name'
````

</details>

<details>
<summary><b>What NoRA does not fill in</b></summary>

NoRA only writes what the sources it reads from actually provide. Zotero and the 
arXiv give the title, authors, abstract, year, venue, identifiers and notes of a 
paper — they do not say which institution an author belongs to, or where their 
homepage is. So **affiliations and author websites are not filled in by NoRA**, in 
either backend, and NoRA no longer references them at all:

- the Notion backend no longer needs an `affiliations_db_id`, no longer creates 
pages in an Affiliations database, and no longer writes the `🏢 Affiliations` or 
`Website` property of a person
- the Obsidian backend no longer creates an `Affiliations` folder, and an author 
note now holds only its `name` and `type`

Before, these were written as empty values — an empty relation on every Notion 
person, `affiliations: []` and a blank `website:` on every Obsidian author note — 
which read like a feature that had stopped working rather than metadata NoRA never 
had in the first place.

**Nothing needs to change on your side.** You can leave the `🏢 Affiliations` 
database and both properties exactly where they are in Notion: NoRA does not touch 
them, so whatever you fill in by hand stays yours, and Notion does not mind a 
property left unset. Deleting them is equally fine.

Two leftovers to know about if you have been using NoRA for a while:

- Your `~/.nora/user.yaml` still lists `notion.affiliations_db_id`, 
`notion.person_keys.affiliations`, `notion.person_keys.website` and 
`obsidian.folders.affiliations`, since `nora configure` writes the whole config out. 
All of them are ignored and there is nothing to clean up: NoRA creates only the 
folders it actually writes to, so deleting `Affiliations/` from your vault is 
enough — it does not come back on the next upload.
- Author notes and person pages created by an earlier version keep their empty 
`affiliations` and `website` values. NoRA never rewrites an entity note it has 
already created, so clearing them is a manual edit — in Obsidian, a one-off 
[Properties](https://help.obsidian.md/properties) sweep over the `People` folder.

The `🏗️ Projects` database of the Notion template is a related but different case. 
NoRA does not write to it either, for the same reason — no source it reads from 
knows which project a paper serves — but the property is worth having, so you can 
assign it by hand. Notion's template already gives you the relation to do that, and 
the Obsidian backend now offers the same through a `projects` property and a 
`Projects` folder: see [assigning papers to 
projects](#assigning-papers-to-projects).

</details>

<details>
<summary><b>
Parsing of `🤹 Conferences & journals` from metadata</b></summary>

By default, when parsing a paper from a remote database, NoRA-Tools will try to 
figure out which `🤹 Conferences & journals` to place it under. To this end, 
the metadata of the searched article will be parsed and matched against a list
of pre-defined conferences and papers. If a match is found, the corresponding
acronym will be attached to the paper in NoRA.

NORA-Tools comes with a predefined set of venue-acronyms matches which can be 
found in the `venues` parameter of your `~/.nora/user.yaml` like so:
```yaml
venues:
    "text to be matched when searching the conference/journal": 'name used in NoRA'
```

When searching for a match, we use the following procedure:
    1. Exact matches of full-text keys (longer first)
    2. Exact matches of acronyms (longer first)
    3. Fuzzy fallback if nothing matches
    4. None if no sufficiently satisfying match is found 

Feel free to edit or extend the `venues` of your  `~/.nora/user.yaml` to suit 
your need and domain of research.

</details>

<details>
<summary><b>
Skipping Zotero collections when migrating your Zotero library</b></summary>

By default, when calling `nora zotero-upload`, the `collections` (i.e. folders) 
in your Zotero library will be used to populate the `Key Topics` field of 
your papers in NoRA. If you want to exclude some of your collections from this 
behavior, your may do so by specifying them in your `~/.nora/user.yaml`:
````yaml
zotero:
    ignored_collections: ['collection name 1', 'collection name 2']
````
</details>

<br>

## 👩‍💻  Contributing

The test suite needs no network, no Node.js and no credentials:

```bash
pip install pytest
PYTHONPATH=src pytest
```

NoRA is organized around a single `Paper` record ([`src/nora/paper.py`](src/nora/paper.py)):
the `parsers` produce one from a source (Zotero, arXiv), and the `sinks` write it 
to a backend (Notion, Obsidian). The two never import each other, so adding a 
backend means writing one `Sink` subclass and registering it in 
[`src/nora/sinks/__init__.py`](src/nora/sinks/__init__.py).

<br>

## License

NoRA is released under the MIT License.

```
MIT License

Copyright (c) 2023-2025 Damien Robert

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
