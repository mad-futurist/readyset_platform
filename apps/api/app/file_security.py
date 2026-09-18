import enum
import socket
from typing import IO, Protocol

from app.config import ScannerBackend, Settings


class ScanResult(str, enum.Enum):
    CLEAN = "clean"
    INFECTED = "infected"
    UNAVAILABLE = "unavailable"


class FileSecurityScanner(Protocol):
    def scan(self, stream: IO[bytes]) -> ScanResult: ...
    def check_available(self) -> None: ...


class NoOpFileSecurityScanner:
    def scan(self, stream: IO[bytes]) -> ScanResult:
        stream.seek(0)
        return ScanResult.CLEAN

    def check_available(self) -> None:
        return None


class FakeFileSecurityScanner(NoOpFileSecurityScanner):
    def __init__(self, result: ScanResult = ScanResult.CLEAN) -> None:
        self.result = result

    def scan(self, stream: IO[bytes]) -> ScanResult:
        stream.seek(0)
        return self.result

    def check_available(self) -> None:
        if self.result == ScanResult.UNAVAILABLE:
            raise ConnectionError("scanner unavailable")


class ClamAVFileSecurityScanner:
    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout

    def _command(self, command: bytes) -> bytes:
        with socket.create_connection((self.host, self.port), self.timeout) as connection:
            connection.sendall(command)
            return connection.recv(4096)

    def check_available(self) -> None:
        if not self._command(b"zPING\0").startswith(b"PONG"):
            raise ConnectionError("scanner unavailable")

    def scan(self, stream: IO[bytes]) -> ScanResult:
        try:
            stream.seek(0)
            with socket.create_connection((self.host, self.port), self.timeout) as connection:
                connection.sendall(b"zINSTREAM\0")
                while chunk := stream.read(64 * 1024):
                    connection.sendall(len(chunk).to_bytes(4, "big") + chunk)
                connection.sendall(b"\x00\x00\x00\x00")
                response = connection.recv(4096)
            stream.seek(0)
        except OSError:
            return ScanResult.UNAVAILABLE
        if b" FOUND" in response:
            return ScanResult.INFECTED
        return ScanResult.CLEAN if b" OK" in response else ScanResult.UNAVAILABLE


def create_file_scanner(settings: Settings) -> FileSecurityScanner:
    if settings.scanner_backend == ScannerBackend.CLAMAV and settings.clamav_host:
        return ClamAVFileSecurityScanner(
            settings.clamav_host, settings.clamav_port, settings.clamav_timeout_seconds
        )
    return NoOpFileSecurityScanner()
