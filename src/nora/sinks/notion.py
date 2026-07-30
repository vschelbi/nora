import time
import requests
import mistletoe
from notional.parser import HtmlParser
from omegaconf import OmegaConf
from typing import Callable, List, Dict, Optional

from nora.paper import Paper
from nora.sinks.base import Sink, SinkError, WriteResult, CREATED, SKIPPED
from nora.utils.keys import sanity_check_config


__all__ = ['NotionLibrary', 'NotionSink']


# The Notion API allows an average of 3 requests per second. Uploading a
# paper with many authors sends dozens of requests in a row, so we space
# them out rather than waiting to be rate-limited
NOTION_REQUEST_PERIOD = 1 / 3

# Number of times a rate-limited or failing request is retried
NOTION_MAX_RETRIES = 5

# Hints helping the user fix the most common Notion API errors
NOTION_ERROR_HINTS = {
    'unauthorized':
        "Check the `notion.token` in your ~/.nora/user.yaml.",
    'restricted_resource':
        "Give your Notion integration permission to access this database.",
    'object_not_found':
        "Check the database IDs in your ~/.nora/user.yaml and make sure your "
        "Notion integration was given access to each database.",
    'validation_error':
        "Notion rejected the data. The fields of your NoRA databases may "
        "differ from the `*_keys` in your ~/.nora/user.yaml.",
}


class NotionLibrary:

    """Holds all static methods for interacting with your Notion
    databases.

    Inspired by:
        https://developers.notion.com/docs/create-a-notion-integration
        python-engineer.com/posts/notion-api-python
        https://developers.notion.com/reference/post-database-query
    """

    # TODO: automatically generate bibtex from notion (maybe parse arxiv first)

    # Time of the last request sent to the Notion API. Held on the class
    # because the rate limit applies to the Notion integration as a
    # whole, rather than to a particular NotionLibrary instance
    _last_request_time = 0.

    def __init__(self, cfg: OmegaConf):
        keys = [
            'token',
            'papers_db_id',
            'people_db_id',
            'venues_db_id',
            'topics_db_id']
        users_keys = [f"notion_{k}" for k in keys]
        sanity_check_config(cfg, keys, users_keys)

        self.cfg = cfg
        self.headers = {
            "authorization": "Bearer " + self.cfg.token,
            "Notion-Version": "2022-06-28",
            "content-type": "application/json"}

    @classmethod
    def _throttle(cls):
        """Space out consecutive requests to stay under the Notion API
        rate limit.
        """
        elapsed = time.monotonic() - cls._last_request_time
        if elapsed < NOTION_REQUEST_PERIOD:
            time.sleep(NOTION_REQUEST_PERIOD - elapsed)
        cls._last_request_time = time.monotonic()

    def _request(self, method: str, url: str, **kwargs):
        """Send a request to the Notion API. Rate limits and transient
        server errors are retried, any other error interrupts the
        program with a readable message rather than a traceback.
        """
        for attempt in range(NOTION_MAX_RETRIES):
            self._throttle()
            response = requests.request(
                method, url, headers=self.headers, **kwargs)

            if response.ok:
                return response

            # Notion tells us how long to wait when we are rate-limited
            if response.status_code == 429:
                delay = float(response.headers.get('Retry-After', 1))
                print(f"⏳ Notion rate limit reached, retrying in {delay:g}s...")
                time.sleep(delay)
                continue

            # Server-side errors are usually transient
            if response.status_code >= 500:
                delay = 2 ** attempt
                print(
                    f"⏳ Notion returned {response.status_code}, retrying in "
                    f"{delay}s...")
                time.sleep(delay)
                continue

            break

        self._fail(response)

    @staticmethod
    def _fail(response: requests.Response):
        """Describe a failed Notion API response and raise. Callers
        uploading many papers can catch this and carry on with the next
        one, rather than losing the whole upload to a single bad item.
        """
        try:
            body = response.json()
        except ValueError:
            body = {}
        code = body.get('code', '')
        message = body.get('message', response.text[:500])

        error = f"Notion API error {response.status_code} ({code}): {message}"
        if code in NOTION_ERROR_HINTS:
            error += f"\n👉 {NOTION_ERROR_HINTS[code]}"
        raise SinkError(error)

    def _relation_ids(
            self,
            names: List[str],
            getter: Callable,
            creator: Callable):
        """Recover the Notion page ids for a list of related items,
        creating the missing pages along the way. The id of a newly
        created page is read from the creation response, to avoid
        searching the database for it again.
        """
        ids = []
        for name in names:
            name = name[:self.cfg.max_text_length]
            item = getter(name_equals=name)
            if len(item) > 0:
                ids.append(item[0]['id'])
                continue
            ids.append(creator(name).json()['id'])
        return ids

    def retrieve_page_from_id(self, page_id: str):
        """Directly retrieve a page from its id.
        """
        url = f"https://api.notion.com/v1/pages/{page_id}"
        return self._request('GET', url).json()

    def _get_pages(
            self,
            database_id: str,
            name_property: str='Name',
            num: int=None,
            name_equals: str=None,
            name_contains: str=None):
        """Get pages from your Notion database.

        The name of the title column is passed in rather than assumed:
        users are free to rename it in their Notion databases, in which
        case filtering on a hardcoded 'Name' would be rejected by the
        API.

        credits: https://www.python-engineer.com/posts/notion-api-python
        """

        # Initialization
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        get_all = num is None
        num = 100 if get_all else num

        # Read first batch of 'num' pages
        payload = {"page_size": num}
        if name_equals:
            payload['filter'] = {
                "property": name_property,
                "rich_text": {
                    "equals": name_equals}}
        elif name_contains:
            payload['filter'] = {
                "property": name_property,
                "rich_text": {
                    "contains": name_contains}}
        data = self._request('POST', url, json=payload).json()
        results = data["results"]

        # If more is needed, read other chunks of 'num' pages
        while data["has_more"] and get_all:
            payload["start_cursor"] = data["next_cursor"]
            data = self._request('POST', url, json=payload).json()
            results.extend(data["results"])

        return results

    def get_people(self, **kwargs):
        """Get person pages from your Notion database.
        """
        return self._get_pages(
            self.cfg.people_db_id,
            name_property=self.cfg.person_keys['name'], **kwargs)

    def get_papers(self, **kwargs):
        """Get paper pages from your Notion database.
        """
        return self._get_pages(
            self.cfg.papers_db_id,
            name_property=self.cfg.paper_keys['name'], **kwargs)

    def get_venues(self, **kwargs):
        """Get venue pages from your Notion database.
        """
        return self._get_pages(
            self.cfg.venues_db_id,
            name_property=self.cfg.venue_keys['name'], **kwargs)

    def get_topics(self, **kwargs):
        """Get topic pages from your Notion database.
        """
        return self._get_pages(
            self.cfg.topics_db_id,
            name_property=self.cfg.topic_keys['name'], **kwargs)

    def get_page_blocks(self, page_id: str):
        url = f"https://api.notion.com/v1/blocks/{page_id}/children"
        return self._request('GET', url).json()["results"]

    def _create_page(self, database_id: str, data: dict):
        url = "https://api.notion.com/v1/pages"
        payload = {'parent': {'database_id': database_id}, 'properties': data}
        return self._request('POST', url, json=payload)

    def create_person(self, name: str, papers: List[str]=[]):
        """Create an author page. Any other property of your People
        database - an affiliation, a website - is left untouched: no
        source NoRA reads from carries that information, so it is yours
        to fill in.
        """
        # Skip if person already exists in the database
        name = name[:self.cfg.max_text_length]
        if len(self.get_people(name_equals=name)) > 0:
            print(f"ℹ️  Person '{name}' already exists")
            return

        data = {
            self.cfg.person_keys['name']: {'title': [
                {'text': {'content': name}}]}}

        # Papers
        paper_ids = self._relation_ids(
            papers, self.get_papers, self.create_paper)
        data[self.cfg.person_keys['papers']] = {
            'relation': [{'id': x} for x in paper_ids]}

        return self._create_page(self.cfg.people_db_id, data)

    def create_paper(
            self,
            name: str,
            authors: List[str]=[],
            topics: List[str]=[],
            to_read: bool=True,
            abstract: str=None,
            url: str=None,
            year: Optional[int]=None,
            venue: str=None):

        # Skip if paper already exists in the database
        name = name[:self.cfg.max_text_length]
        if len(self.get_papers(name_equals=name)) > 0:
            print(f"ℹ️  Paper '{name}' already exists")
            return

        data = {
            self.cfg.paper_keys['name']: {'title': [
                {'text': {'content': name}}]}}

        # Authors
        author_ids = self._relation_ids(
            authors, self.get_people, self.create_person)
        data[self.cfg.paper_keys['authors']] = {
            'relation': [{'id': x} for x in author_ids]}

        # Topic
        topic_ids = self._relation_ids(
            topics, self.get_topics, self.create_topic)
        data[self.cfg.paper_keys['topics']] = {
            'relation': [{'id': x} for x in topic_ids]}

        # Read status
        data[self.cfg.paper_keys['to_read']] = {
            'status': {'name': 'Not started' if to_read else 'Done'}}

        # Abstract. Line breaks and hyphenated splits have already been
        # cleaned up by nora.paper.normalize_abstract
        if abstract is not None:
            data[self.cfg.paper_keys['abstract']] = {
                'rich_text': [
                    {'text': {'content': abstract[:self.cfg.max_text_length]}}]}

        # URL
        if url is not None and url != '':
            data[self.cfg.paper_keys['url']] = {
                'url': url[:self.cfg.max_text_length]}

        # Year
        if year is not None:
            data[self.cfg.paper_keys['year']] = {'number': year}

        # Venue
        if venue is not None:
            venue_ids = self._relation_ids(
                [venue], self.get_venues, self.create_venue)
            data[self.cfg.paper_keys['venue']] = {
                'relation': [{'id': x} for x in venue_ids]}

        return self._create_page(self.cfg.papers_db_id, data)

    def create_venue(self, name: str):
        # Skip if venue already exists in the database
        name = name[:self.cfg.max_text_length]
        if len(self.get_venues(name_equals=name)) > 0:
            print(f"ℹ️  Venue '{name}' already exists")
            return

        # Prepare the Notion API json
        data = {
            self.cfg.venue_keys['name']: {
                'title': [{'text': {'content': name}}]}}

        return self._create_page(self.cfg.venues_db_id, data)

    def create_topic(self, name: str):
        # Skip if topic already exists in the database
        name = name[:self.cfg.max_text_length]
        if len(self.get_topics(name_equals=name)) > 0:
            print(f"ℹ️  Topic '{name}' already exists")
            return

        # Prepare the Notion API json
        data = {
            self.cfg.topic_keys['name']: {
                'title': [{'text': {'content': name}}]}}

        return self._create_page(self.cfg.topics_db_id, data)

    def append_page_blocks(self, page_id: str, text: str):
        # Convert input HTML text to Notion API json
        html_text = mistletoe.markdown(text)
        parser = HtmlParser()
        parser.parse(html_text)
        notion_text = [x.dict() for x in parser.content]

        # The Notion API only supports a limited depth for nested items
        # This can cause errors if we have overly-deep bullet lists, for
        # instance. So we flatten all the text beyond a certain depth
        notion_text = self._flatten_max_depth_children(
            notion_text, max_depth=2, marker='•')

        # Append text to page blocks
        url = f"https://api.notion.com/v1/blocks/{page_id}/children"
        payload = {'children': notion_text}
        return self._request('PATCH', url, json=payload)

    def _update_page(self, page_id: str, data: dict):
        url = f"https://api.notion.com/v1/pages/{page_id}"
        payload = {"properties": data}
        return self._request('PATCH', url, json=payload)

    def _flatten_block(
            self,
            block: Dict,
            marker: str='•',
            depth: int=1):
        text = ' '.join(
            [x['text']['content'] for x in block[block['type']]['rich_text']])

        if not block['has_children']:
            return text

        text += " ( "

        for child in block[block['type']]['children']:
            flat_child = self._flatten_block(
                child, marker=marker, depth=depth + 1)
            text += f" {marker * depth} {flat_child}"

        text += " ) "

        return text

    def _flatten_children(
            self,
            block: Dict,
            marker: str='•',
            depth: int=1):
        if not block['has_children']:
            return block

        # Recursively flatten and wrap the content of descendent blocks
        text = " ( "
        for child in block[block['type']]['children']:
            flat_child = self._flatten_block(
                child, marker=marker, depth=depth + 1)
            text += f" {marker * depth} {flat_child}"
        text += " ) "

        # Create a new text block containing the flattened children text
        block[block['type']]['rich_text'].append(
            {'type': 'text', 'text': {'content': text}})
        block['has_children'] = False
        del block[block['type']]['children']

        return block

    def _flatten_max_depth_children(
            self,
            blocks: List[Dict],
            depth: int=0,
            max_depth: int=2,
            marker: str='•'):
        for i, block in enumerate(blocks):
            if not block['has_children']:
                continue

            if depth >= max_depth:
                blocks[i] = self._flatten_children(
                    block, marker=marker)
                continue

            self._flatten_max_depth_children(
                block[block['type']]['children'], depth=depth + 1,
                max_depth=max_depth, marker=marker)

        return blocks

    def __repr__(self):
        return f"{self.__class__.__name__}()"


class NotionSink(Sink):

    """Write papers to a set of interconnected Notion databases.
    """

    name = 'notion'

    def __init__(self, cfg: OmegaConf):
        super().__init__(cfg)
        self.library = NotionLibrary(cfg)

    def write(self, paper: Paper):
        response = self.library.create_paper(
            paper.title,
            authors=paper.authors,
            topics=paper.topics,
            to_read=paper.to_read,
            abstract=paper.abstract,
            url=paper.url,
            year=paper.year,
            venue=paper.venue)

        # create_paper returns None when a same-titled page already
        # exists in the database
        if response is None:
            return WriteResult(SKIPPED, message="already in Notion")

        page_id = response.json()['id']

        # Create the blocks (free text) from the notes
        if paper.notes:
            self.library.append_page_blocks(page_id, paper.notes)

        return WriteResult(CREATED, ref=page_id)
