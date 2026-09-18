import io
import zipfile
from typing import IO


class InvalidFileContent(ValueError):
    pass


PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT = {"text/plain", "text/markdown"}


def validate_content(stream: IO[bytes], declared_type: str) -> str:
    """Validate bounded staged content and return its normalized MIME type."""
    stream.seek(0)
    data = stream.read()
    stream.seek(0)
    declared = declared_type.split(";", 1)[0].strip().lower()
    if data.startswith(b"%PDF-"):
        header = data[:8]
        if len(data) < 12 or header[5:8] not in {
            b"1.0", b"1.1", b"1.2", b"1.3", b"1.4", b"1.5", b"1.6", b"1.7", b"2.0"
        } or b"%%EOF" not in data[-2048:]:
            raise InvalidFileContent("Invalid PDF content")
        actual = PDF
    elif data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                if not {"[Content_Types].xml", "word/document.xml"} <= names:
                    raise InvalidFileContent("Invalid DOCX content")
                if any(info.flag_bits & 0x1 for info in archive.infolist()):
                    raise InvalidFileContent("Encrypted DOCX files are not supported")
                if sum(info.file_size for info in archive.infolist()) > max(len(data) * 100, 50_000_000):
                    raise InvalidFileContent("DOCX expansion is unreasonable")
        except (zipfile.BadZipFile, OSError) as exc:
            raise InvalidFileContent("Invalid DOCX content") from exc
        actual = DOCX
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise InvalidFileContent("Text files must be valid UTF-8") from exc
        if "\x00" in text:
            raise InvalidFileContent("Binary content is not accepted as text")
        controls = sum(ord(char) < 32 and char not in "\n\r\t" for char in text)
        if controls > max(2, len(text) // 100):
            raise InvalidFileContent("Binary content is not accepted as text")
        actual = declared if declared in TEXT else "text/plain"
    if actual != declared:
        raise InvalidFileContent("Declared file type does not match content")
    return actual
