import json

import pytest

import nora.utils.translation_server as ts


CHOICES = {
    'url': 'https://example.org/preprint',
    'session': 'abc123',
    'items': {'https://example.org/article': 'Published version'}}

ITEM = [{'itemType': 'journalArticle', 'title': 'Published version'}]


@pytest.fixture
def server(monkeypatch):
    """Replace the translation server by a queue of canned responses,
    and record what was sent to it.
    """
    sent = []
    responses = []

    def post_to_server(endpoint, data, content_type="text/plain", timeout=20):
        sent.append((endpoint, data, content_type))
        return responses.pop(0)

    monkeypatch.setattr(ts, 'start_server', lambda: None)
    monkeypatch.setattr(ts, 'post_to_server', post_to_server)
    return sent, responses


def test_translate_from_url_returns_a_single_item(server):
    sent, responses = server
    responses.append((json.dumps(ITEM), 200))

    item = ts.translate_from_url('https://example.org/article')

    assert item['data']['itemType'] == 'journalArticle'
    assert len(sent) == 1


def test_translate_from_url_follows_a_single_choice(server):
    # A preprint page pointing to its published version
    sent, responses = server
    responses += [(json.dumps(CHOICES), 300), (json.dumps(ITEM), 200)]

    item = ts.translate_from_url(CHOICES['url'])

    assert item['data']['title'] == 'Published version'
    endpoint, data, content_type = sent[1]
    assert endpoint == 'web'
    assert content_type == 'application/json'
    assert json.loads(data) == CHOICES


def test_translate_from_url_asks_among_several_choices(server, monkeypatch):
    sent, responses = server
    choices = {**CHOICES, 'items': {'a': 'First', 'b': 'Second'}}
    responses += [(json.dumps(choices), 300), (json.dumps(ITEM), 200)]
    answers = iter(['', '3', '2'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))

    ts.translate_from_url(CHOICES['url'])

    assert json.loads(sent[1][1])['items'] == {'b': 'Second'}


def test_translate_from_url_exits_when_no_choice_is_made(server, monkeypatch):
    _, responses = server
    choices = {**CHOICES, 'items': {'a': 'First', 'b': 'Second'}}
    responses.append((json.dumps(choices), 300))

    def interrupted(_):
        raise EOFError
    monkeypatch.setattr('builtins.input', interrupted)

    with pytest.raises(SystemExit):
        ts.translate_from_url(CHOICES['url'])


def test_json_to_python_rejects_a_response_without_an_item():
    with pytest.raises(SystemExit):
        ts.json_to_python(json.dumps(CHOICES))
