import hashlib
from dataclasses import dataclass
from typing import Any

import tiktoken

from app.knowledge.extraction import ExtractedDocument


class TokenCounter:
    def __init__(self, encoding: str = "cl100k_base") -> None:
        self.encoding = tiktoken.get_encoding(encoding)

    def count(self, text: str) -> int:
        return len(self.encoding.encode(text, disallowed_special=()))

    def prefix(self, text: str, limit: int) -> str:
        if self.count(text) <= limit:
            return text
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if self.count(text[:middle]) <= limit:
                low = middle
            else:
                high = middle - 1
        return text[:low]


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str
    token_count: int
    source_locator: dict[str, Any]
    heading_path: list[str]
    content_sha256: str


class StructureChunker:
    def __init__(self, target: int, maximum: int, tokenizer: str = "cl100k_base") -> None:
        self.target, self.maximum = target, maximum
        if not 0 < target <= maximum:
            raise ValueError("Invalid token bounds")
        self.tokens = TokenCounter(tokenizer)
        self.identity = f"structure-v1:{tokenizer}:target={target}:max={maximum}:overlap=0"

    def chunk(self, document: ExtractedDocument) -> list[Chunk]:
        output: list[Chunk] = []
        parts: list[str] = []
        spans: list[dict[str, Any]] = []
        headings: list[str] = []
        boundary: tuple[object, ...] | None = None

        def flush() -> None:
            if not parts:
                return
            text = "\n\n".join(parts)
            locator = {**spans[0], "spans": spans.copy()}
            if locator.get("kind") in {"text", "markdown"}:
                locator["line_end"] = spans[-1]["line_end"]
            output.append(Chunk(len(output), text, self.tokens.count(text), locator,
                                headings.copy(), hashlib.sha256(text.encode()).hexdigest()))
            parts.clear()
            spans.clear()

        for block in document.blocks:
            if not block.text.strip():
                continue
            current_boundary = (*block.heading_path, block.source_locator.get("page"), block.source_locator["kind"])
            if boundary != current_boundary:
                flush()
                boundary, headings = current_boundary, block.heading_path
            remaining = block.text
            offset = 0
            while remaining:
                prefix = self.tokens.prefix(remaining, self.maximum)
                if not prefix:
                    raise ValueError("Token bound cannot hold a Unicode character")
                if len(prefix) < len(remaining):
                    split = max(prefix.rfind("\n"), prefix.rfind(" "))
                    if split > len(prefix) // 2:
                        prefix = prefix[:split + 1]
                if parts and self.tokens.count("\n\n".join([*parts, prefix])) > self.maximum:
                    flush()
                parts.append(prefix)
                spans.append({**block.source_locator, "block_order": block.order,
                              "character_start": offset, "character_end": offset + len(prefix)})
                remaining = remaining[len(prefix):]
                offset += len(prefix)
                if remaining or self.tokens.count("\n\n".join(parts)) >= self.target:
                    flush()
        flush()
        return output
