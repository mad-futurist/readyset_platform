from collections.abc import Iterator
from typing import IO, Protocol

import boto3

from app.config import Settings


class ObjectStorage(Protocol):
    def put_stream(self, key: str, stream: IO[bytes], content_type: str) -> None: ...
    def iter_bytes(self, key: str) -> Iterator[bytes]: ...
    def delete(self, key: str) -> None: ...


class S3ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.storage_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url,
            aws_access_key_id=settings.storage_access_key,
            aws_secret_access_key=settings.storage_secret_key,
            region_name=settings.storage_region,
        )

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)

    def put_stream(self, key: str, stream: IO[bytes], content_type: str) -> None:
        self.client.upload_fileobj(
            stream, self.bucket, key, ExtraArgs={"ContentType": content_type}
        )

    def iter_bytes(self, key: str) -> Iterator[bytes]:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        try:
            while chunk := body.read(64 * 1024):
                yield chunk
        finally:
            body.close()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


class MemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_stream(self, key: str, stream: IO[bytes], content_type: str) -> None:
        self.objects[key] = stream.read()

    def iter_bytes(self, key: str) -> Iterator[bytes]:
        yield self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)
