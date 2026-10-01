import logging
import re
import zipfile
from dataclasses import asdict, dataclass
from importlib.metadata import version
from typing import IO, Any, Protocol

from docx import Document as OpenDocument
from docx.table import Table
from pypdf import PdfReader

from app.config import Settings


class ExtractionError(RuntimeError):
    def __init__(self, code: str = "invalid_source") -> None:
        self.code = code
        super().__init__("This file could not be processed.")


@dataclass(frozen=True)
class Block:
    type: str
    text: str
    heading_path: list[str]
    source_locator: dict[str, Any]
    order: int


@dataclass(frozen=True)
class ExtractedDocument:
    blocks: list[Block]
    extractor: str

    def serialize(self) -> list[dict[str, Any]]:
        return [asdict(block) for block in self.blocks]


class DocumentExtractor(Protocol):
    def extract(self, source: IO[bytes], mime_type: str) -> ExtractedDocument: ...


class StructuredExtractor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract(self, source: IO[bytes], mime_type: str) -> ExtractedDocument:
        blocks: list[Block] = []
        characters = 0

        def add(kind: str, text: str, headings: list[str], locator: dict[str, Any]) -> None:
            nonlocal characters
            text = text.strip()
            if not text:
                return
            characters += len(text)
            if characters > self.settings.extraction_max_characters or len(blocks) >= self.settings.extraction_max_blocks:
                raise ExtractionError("extraction_limit")
            if "\x00" in text:
                raise ExtractionError()
            blocks.append(Block(kind, text, headings.copy(), locator, len(blocks)))

        try:
            if mime_type == "application/pdf":
                # Third-party parser diagnostics can include enterprise source fragments.
                logging.getLogger("pypdf").setLevel(logging.CRITICAL)
                reader = PdfReader(source, strict=True)
                if reader.is_encrypted:
                    raise ExtractionError("encrypted_source")
                if len(reader.pages) > self.settings.extraction_max_pages:
                    raise ExtractionError("extraction_limit")
                for page_number, page in enumerate(reader.pages, 1):
                    content = page.get_contents()
                    if content and len(content.get_data()) > self.settings.extraction_max_characters * 8:
                        raise ExtractionError("extraction_limit")
                    page_text = page.extract_text() or ""
                    for paragraph in re.split(r"\n\s*\n", page_text):
                        add("paragraph", paragraph, [], {"kind": "pdf", "page": page_number})
                extractor = f"pdf-v1:pypdf-{version('pypdf')}"
            elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                with zipfile.ZipFile(source) as archive:
                    if sum(item.file_size for item in archive.infolist()) > self.settings.extraction_max_characters * 8:
                        raise ExtractionError("extraction_limit")
                source.seek(0)
                document = OpenDocument(source)
                headings: list[str] = []
                paragraph_number, table_number = 0, 0
                for body_index, item in enumerate(document.iter_inner_content(), 1):
                    locator: dict[str, Any] = {"kind": "docx", "body_index": body_index}
                    if isinstance(item, Table):
                        table_number += 1
                        locator["table"] = table_number
                        text = "\n".join(" | ".join(cell.text for cell in row.cells) for row in item.rows)
                        add("table_text", text, headings, locator)
                    else:
                        paragraph_number += 1
                        locator["paragraph_start"] = paragraph_number
                        style = item.style.name if item.style else ""
                        match = re.fullmatch(r"Heading (\d+)", style or "")
                        if match:
                            level = int(match[1])
                            headings = headings[:level - 1] + [item.text]
                        locator["heading_path"] = headings.copy()
                        kind = "heading" if match else "list" if "List" in (style or "") else "paragraph"
                        add(kind, item.text, headings, locator)
                extractor = f"docx-v1:python-docx-{version('python-docx')}"
            elif mime_type in {"text/plain", "text/markdown"}:
                raw = source.read(self.settings.max_upload_bytes + 1)
                if len(raw) > self.settings.max_upload_bytes:
                    raise ExtractionError("extraction_limit")
                text = raw.decode("utf-8-sig")
                markdown = mime_type == "text/markdown"
                headings = []
                lines = text.splitlines()
                pending: list[str] = []
                start = 1
                fence: str | None = None

                def flush(end: int) -> None:
                    if pending:
                        add("code" if fence else "paragraph", "\n".join(pending), headings,
                            {"kind": "markdown" if markdown else "text", "line_start": start, "line_end": end, "heading_path": headings.copy()})
                        pending.clear()

                for number, line in enumerate(lines, 1):
                    heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line) if markdown and not fence else None
                    marker = re.match(r"^\s*(`{3,}|~{3,})", line) if markdown else None
                    if marker:
                        if fence:
                            pending.append(line)
                            flush(number)
                            fence = None
                        else:
                            flush(number - 1)
                            fence = marker[1][0]
                            start = number
                            pending.append(line)
                    elif heading:
                        flush(number - 1)
                        headings = headings[:len(heading[1]) - 1] + [heading[2]]
                        add("heading", heading[2], headings, {"kind": "markdown", "line_start": number, "line_end": number, "heading_path": headings.copy()})
                    elif not line.strip() and not fence:
                        flush(number - 1)
                    else:
                        if not pending:
                            start = number
                        pending.append(line)
                flush(len(lines))
                extractor = "markdown-lines-v1" if markdown else "utf8-lines-v1"
            else:
                raise ExtractionError("unsupported_source")
        except ExtractionError:
            raise
        except Exception:
            # Never include a parser exception (paths, XML or source text) in public state.
            raise ExtractionError() from None
        if not blocks:
            raise ExtractionError("no_extractable_text")
        return ExtractedDocument(blocks, extractor)
