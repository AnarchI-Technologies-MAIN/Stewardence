from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

PDF_CONTENT_TYPE = "application/pdf"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ReportStorageError(RuntimeError):
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

        if path.exists():
            raise ReportStorageError("Report object already exists")

        path.write_bytes(content)

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
            return body.read()
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
            )
        except (BotoCoreError, ClientError) as error:
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
