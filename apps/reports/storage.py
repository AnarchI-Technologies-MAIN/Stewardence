from __future__ import annotations

import hashlib
import os
import tempfile
import re
import uuid
from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from apps.jobs.recovery import ReplaySafeErrorWrapper

PDF_CONTENT_TYPE = "application/pdf"
MAX_PDF_BYTES = 16 * 1_048_576
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ReportStorageError(ReplaySafeErrorWrapper):
    pass


class PrivateReportStorage(Protocol):
    def put(self, *, key: str, content: bytes, content_type: str) -> None: ...

    def get(self, *, key: str) -> bytes: ...

    def delete(self, *, key: str) -> None: ...


def build_pdf_object_key(
    *,
    organization_id: uuid.UUID,
    assessment_snapshot_id: uuid.UUID,
    report_id: uuid.UUID,
) -> str:
    return (
        f"organizations/{organization_id}/"
        f"assessments/{assessment_snapshot_id}/"
        f"reports/{report_id}.pdf"
    )


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_pdf_bytes(content: bytes) -> None:
    if not isinstance(content, bytes):
        raise ReportStorageError("Report artifact content must be bytes")
    if not content:
        raise ReportStorageError("Report artifact cannot be empty")
    if len(content)>MAX_PDF_BYTES:
        raise ReportStorageError('Report artifact exceeds its size bound')
    if not content.startswith(b"%PDF-"):
        raise ReportStorageError("Report artifact is not a PDF")


class LocalPrivateReportStorage:
    """
    Development/test backend only.

    This backend proves the private-storage contract locally. It is not the
    production reports bucket and must never be represented as production
    object-storage evidence.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path_for_key(self, key: str) -> Path:
        if not key or key.startswith(("/", "\\")):
            raise ReportStorageError("Invalid report object key")

        candidate = (self.root / key).resolve()

        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise ReportStorageError(
                "Report object key escapes storage root"
            ) from error

        return candidate

    def put(self, *, key: str, content: bytes, content_type: str) -> None:
        if content_type != PDF_CONTENT_TYPE:
            raise ReportStorageError("Unsupported report artifact content type")

        validate_pdf_bytes(content)

        path = self._path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".report-")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Publish a complete private file without replacing an existing key.
                os.link(temporary, path)
            except FileExistsError as error:
                if path.read_bytes() == content:
                    return
                raise ReportStorageError("Report object already exists") from error
        finally:
            Path(temporary).unlink(missing_ok=True)

    def get(self, *, key: str) -> bytes:
        path = self._path_for_key(key)

        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise ReportStorageError("Report object does not exist") from error

    def delete(self, *, key: str) -> None:
        path = self._path_for_key(key)

        try:
            path.unlink()
        except FileNotFoundError:
            return


class S3PrivateReportStorage:
    """
    Private S3-compatible production report storage.

    The object key is deterministic but is never an authorization token.
    Authorization remains in the application/RLS/report-ownership boundary.
    """

    _NOT_FOUND_CODES = frozenset(
        {
            "404",
            "NoSuchKey",
            "NotFound",
        }
    )

    def __init__(
        self,
        *,
        bucket_name: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region_name: str = "auto",
        addressing_style: str = "virtual",
        client=None,
    ):
        if not bucket_name:
            raise ImproperlyConfigured("REPORTS_BUCKET_NAME is required")
        if not endpoint_url:
            raise ImproperlyConfigured("REPORTS_BUCKET_ENDPOINT is required")
        if not access_key_id:
            raise ImproperlyConfigured("REPORTS_BUCKET_ACCESS_KEY_ID is required")
        if not secret_access_key:
            raise ImproperlyConfigured("REPORTS_BUCKET_SECRET_ACCESS_KEY is required")
        if addressing_style not in {"virtual", "path"}:
            raise ImproperlyConfigured(
                "REPORTS_BUCKET_URL_STYLE must be virtual or path"
            )

        self.bucket_name = bucket_name

        if client is not None:
            self.client = client
            return

        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name,
            config=Config(
                connect_timeout=10,
                read_timeout=30,
                retries={"max_attempts":1},
                s3={
                    "addressing_style": addressing_style,
                }
            ),
        )

    @classmethod
    def _is_not_found(cls, error: ClientError) -> bool:
        code = str(error.response.get("Error", {}).get("Code", ""))
        return code in cls._NOT_FOUND_CODES

    def _read_optional(self, key: str) -> bytes | None:
        try:
            response = self.client.get_object(
                Bucket=self.bucket_name,
                Key=key,
            )
            body = response["Body"]
            try:
                if response.get('ContentLength',0)>MAX_PDF_BYTES:
                    raise ReportStorageError('Private report object exceeds its size bound')
                content=body.read(MAX_PDF_BYTES+1)
                if len(content)>MAX_PDF_BYTES:
                    raise ReportStorageError('Private report object exceeds its size bound')
                return content
            finally:
                close=getattr(body,'close',None)
                if close is not None: close()
        except ClientError as error:
            if self._is_not_found(error):
                return None
            raise ReportStorageError("Private report object read failed") from error
        except BotoCoreError as error:
            raise ReportStorageError("Private report object read failed") from error

    def put(self, *, key: str, content: bytes, content_type: str) -> None:
        if content_type != PDF_CONTENT_TYPE:
            raise ReportStorageError("Unsupported report artifact content type")

        validate_pdf_bytes(content)

        existing = self._read_optional(key)

        if existing is not None:
            if existing == content:
                return
            raise ReportStorageError(
                "Report object already exists with different content"
            )

        try:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=content,
                ContentType=content_type,
                ACL='private',
                IfNoneMatch="*",
            )
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"412", "PreconditionFailed", "409", "ConditionalRequestConflict"}:
                if self._read_optional(key) == content:
                    return
                raise ReportStorageError("Report object creation conflict") from error
            raise ReportStorageError("Private report object upload failed") from error
        except BotoCoreError as error:
            raise ReportStorageError("Private report object upload failed") from error

    def get(self, *, key: str) -> bytes:
        content = self._read_optional(key)

        if content is None:
            raise ReportStorageError("Report object does not exist")

        return content

    def delete(self, *, key: str) -> None:
        try:
            self.client.delete_object(
                Bucket=self.bucket_name,
                Key=key,
            )
        except (BotoCoreError, ClientError) as error:
            raise ReportStorageError("Private report object cleanup failed") from error


def build_private_report_storage(
    local_root: Path | None = None,
) -> PrivateReportStorage:
    backend = getattr(
        settings,
        "REPORTS_STORAGE_BACKEND",
        "local",
    )

    if backend == "local":
        root = local_root

        if root is None:
            root = getattr(
                settings,
                "REPORTS_LOCAL_STORAGE_ROOT",
                None,
            )

        if root is None:
            raise ImproperlyConfigured(
                "REPORTS_LOCAL_STORAGE_ROOT is required for local report storage"
            )

        return LocalPrivateReportStorage(Path(root))

    if backend == "s3":
        return S3PrivateReportStorage(
            bucket_name=getattr(settings, "REPORTS_BUCKET_NAME", ""),
            endpoint_url=getattr(settings, "REPORTS_BUCKET_ENDPOINT", ""),
            access_key_id=getattr(
                settings,
                "REPORTS_BUCKET_ACCESS_KEY_ID",
                "",
            ),
            secret_access_key=getattr(
                settings,
                "REPORTS_BUCKET_SECRET_ACCESS_KEY",
                "",
            ),
            region_name=getattr(
                settings,
                "REPORTS_BUCKET_REGION",
                "auto",
            ),
            addressing_style=getattr(
                settings,
                "REPORTS_BUCKET_URL_STYLE",
                "virtual",
            ),
        )

    raise ImproperlyConfigured("REPORTS_STORAGE_BACKEND must be local or s3")
