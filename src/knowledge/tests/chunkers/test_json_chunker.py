import json

from chunkers.json_chunker import JSONChunker


def test_chunk_array_rooted_json_does_not_raise():
    text = json.dumps([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])

    chunks = JSONChunker(2000, 200, {}).chunk(text)

    assert chunks


def test_chunk_object_rooted_json_does_not_raise():
    text = json.dumps({"users": [{"id": 1, "name": "a"}], "meta": {"total": 1}})

    chunks = JSONChunker(2000, 200, {}).chunk(text)

    assert chunks


def test_chunk_array_rooted_json_preserves_content():
    text = json.dumps([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])

    chunks = JSONChunker(2000, 200, {}).chunk(text)
    combined_text = "".join(chunk.text for chunk in chunks)

    assert '"id"' in combined_text
    assert "1" in combined_text
    assert '"name"' in combined_text
    assert '"a"' in combined_text
