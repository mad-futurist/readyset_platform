import io
from pathlib import Path

import pytest

from app.config import Settings
from app.knowledge.chunking import StructureChunker
from app.knowledge.extraction import Block, ExtractedDocument, ExtractionError, StructuredExtractor

pytestmark = pytest.mark.worker
FIXTURES = Path(__file__).parent / "fixtures" / "ingestion"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.mark.parametrize(("filename", "mime", "kind"), [
    ("policies.pdf", "application/pdf", "pdf"), ("deployment.docx", DOCX, "docx"),
    ("deployment.md", "text/markdown", "markdown"), ("unicode.txt", "text/plain", "text"),
])
def test_golden_order_locators_and_determinism(filename: str, mime: str, kind: str) -> None:
    extractor = StructuredExtractor(Settings())
    with (FIXTURES / filename).open("rb") as source:
        result = extractor.extract(source, mime)
        source.seek(0)
        assert extractor.extract(source, mime) == result
    assert [block.order for block in result.blocks] == list(range(len(result.blocks)))
    assert all(block.source_locator["kind"] == kind for block in result.blocks)
    chunker = StructureChunker(30, 60)
    assert chunker.chunk(result) == chunker.chunk(result)
    assert all(0 < chunk.token_count <= 60 for chunk in chunker.chunk(result))
    if kind == "pdf":
        assert [block.source_locator["page"] for block in result.blocks] == [1, 3]
        assert "Security policy" in result.blocks[0].text
        assert "support desk" in result.blocks[1].text
    elif kind == "docx":
        table = next(block for block in result.blocks if block.type == "table_text")
        assert "Paris | 30 days" in table.text
        assert table.heading_path == ["Deployment", "Backups"]
        assert table.source_locator["table"] == 1
        assert table.source_locator["body_index"] == 4
        assert result.blocks[-1].source_locator["paragraph_start"] == 4
        assert "Україна" in result.blocks[-1].text
    elif kind == "markdown":
        assert result.blocks[2].heading_path == ["Deployment", "Backups"]
        assert result.blocks[2].source_locator["line_start"] == 5
        assert next(block for block in result.blocks if block.type == "code").source_locator["line_end"] == 11
    else:
        assert result.blocks[0].source_locator["line_end"] == 2
        assert "東京" in result.blocks[0].text


@pytest.mark.parametrize(("filename", "mime"), [("malformed.pdf", "application/pdf"), ("malformed.docx", DOCX)])
def test_malformed_sources_have_sanitized_errors(filename: str, mime: str) -> None:
    with (FIXTURES / filename).open("rb") as source, pytest.raises(ExtractionError) as failure:
        StructuredExtractor(Settings()).extract(source, mime)
    assert str(failure.value) == "This file could not be processed."


def test_tiny_headings_empty_blocks_long_unicode_and_exact_bounds() -> None:
    text = "Україна café 東京🙂 " * 400
    document = ExtractedDocument([
        Block("heading", "Security", ["Security"], {"kind": "text", "line_start": 1, "line_end": 1}, 0),
        Block("paragraph", "", [], {"kind": "text"}, 1),
        Block("paragraph", text, ["Security"], {"kind": "text", "line_start": 2, "line_end": 2}, 2),
    ], "test-v1")
    chunks = StructureChunker(16, 32).chunk(document)
    assert len(chunks) > 1
    assert all(chunk.token_count <= 32 and "�" not in chunk.text for chunk in chunks)
    assert all(chunk.heading_path == ["Security"] for chunk in chunks)
    # No lost or duplicated Unicode bytes across long-block splits.
    spans = [span for chunk in chunks for span in chunk.source_locator["spans"] if span["block_order"] == 2]
    assert spans[0]["character_start"] == 0
    assert spans[-1]["character_end"] == len(text)
    assert all(left["character_end"] == right["character_start"] for left, right in zip(spans, spans[1:], strict=False))
    tiny = StructuredExtractor(Settings()).extract(io.BytesIO(b"tiny"), "text/plain")
    assert StructureChunker(16, 32).chunk(tiny)[0].text == "tiny"


def test_empty_and_oversized_extraction_fails_closed() -> None:
    with pytest.raises(ExtractionError, match="could not be processed"):
        StructuredExtractor(Settings()).extract(io.BytesIO(b"\n\n"), "text/plain")
    with pytest.raises(ExtractionError) as failure:
        StructuredExtractor(Settings(extraction_max_characters=1000)).extract(io.BytesIO(b"a" * 1001), "text/plain")
    assert failure.value.code == "extraction_limit"
