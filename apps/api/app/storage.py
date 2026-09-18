from collections.abc import Iterator
from typing import IO, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings, StorageEncryption


class StorageError(RuntimeError):
    pass


class ObjectNotFound(StorageError):
    pass


class StorageUnavailable(StorageError):
    pass


class StoragePermissionDenied(StorageError):
    pass


class ObjectStorage(Protocol):
    def put_stream(self, key: str, stream: IO[bytes], content_type: str) -> None: ...
    def iter_bytes(self, key: str) -> Iterator[bytes]: ...
    def delete(self, key: str) -> None: ...
    def check_access(self) -> None: ...


class S3ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.storage_bucket
        self.auto_create_bucket = settings.storage_auto_create_bucket
        self.extra_args: dict[str, str] = {}
        if settings.storage_encryption != StorageEncryption.NONE:
            self.extra_args["ServerSideEncryption"] = settings.storage_encryption.value
        if settings.storage_encryption == StorageEncryption.KMS and settings.storage_kms_key_id:
            self.extra_args["SSEKMSKeyId"] = settings.storage_kms_key_id
        client_args: dict[str, object] = {
            "endpoint_url": settings.storage_endpoint_url,
            "region_name": settings.storage_region,
        }
        if settings.storage_access_key and settings.storage_secret_key:
            client_args.update(
                aws_access_key_id=settings.storage_access_key,
                aws_secret_access_key=settings.storage_secret_key,
            )
        self.client = boto3.client("s3", **client_args)

    @staticmethod
    def _translate(exc: Exception) -> StorageError:
        if isinstance(exc, ClientError):
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"NoSuchKey", "404"} or status == 404:
                return ObjectNotFound("Object not found")
            if code in {"AccessDenied", "Forbidden", "InvalidAccessKeyId", "SignatureDoesNotMatch"} or status == 403:
                return StoragePermissionDenied("Object storage permission denied")
        return StorageUnavailable("Object storage is unavailable")

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if self.auto_create_bucket and (status == 404 or code in {"404", "NoSuchBucket"}):
                try:
                    self.client.create_bucket(Bucket=self.bucket)
                    return
                except (ClientError, BotoCoreError) as create_exc:
                    raise self._translate(create_exc) from create_exc
            raise self._translate(exc) from exc
        except BotoCoreError as exc:
            raise self._translate(exc) from exc

    def check_access(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except (ClientError, BotoCoreError) as exc:
            raise self._translate(exc) from exc

    def put_stream(self, key: str, stream: IO[bytes], content_type: str) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=stream,
                ContentType=content_type,
                **self.extra_args,
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._translate(exc) from exc

    def iter_bytes(self, key: str) -> Iterator[bytes]:
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except (ClientError, BotoCoreError) as exc:
            raise self._translate(exc) from exc
        try:
            while chunk := body.read(64 * 1024):
                yield chunk
        finally:
            body.close()

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise self._translate(exc) from exc


class MemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_stream(self, key: str, stream: IO[bytes], content_type: str) -> None:
        self.objects[key] = stream.read()

    def iter_bytes(self, key: str) -> Iterator[bytes]:
        yield self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def check_access(self) -> None:
        return None
