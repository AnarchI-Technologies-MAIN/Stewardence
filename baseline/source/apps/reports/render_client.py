from __future__ import annotations

from typing import Any, Protocol

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .storage import PDF_CONTENT_TYPE, ReportStorageError, validate_pdf_bytes

MAX_RENDERED_PDF_BYTES = 16 * 1_048_576


class ReportRenderError(RuntimeError):
    pass


class ReportRenderer(Protocol):
    def render(self, report_context: dict[str, Any]) -> bytes: ...


class HTTPReportRenderer:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 70.0,
        transport=None,
    ):
        if not base_url:
            raise ImproperlyConfigured("REPORT_RENDERER_URL is required")

        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def render(self, report_context: dict[str, Any]) -> bytes:
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    f"{self.base_url}/v1/render",
                    json=report_context,
                    headers={
                        "Accept": PDF_CONTENT_TYPE,
                    },
                )
        except httpx.HTTPError as error:
            raise ReportRenderError("Report renderer request failed") from error

        if response.status_code != 200:
            raise ReportRenderError(
                f"Report renderer returned HTTP {response.status_code}"
            )

        content_type = (
            response.headers.get(
                "Content-Type",
                "",
            )
            .split(";", 1)[0]
            .strip()
            .lower()
        )

        if content_type != PDF_CONTENT_TYPE:
            raise ReportRenderError(
                "Report renderer returned an unexpected content type"
            )

        content = response.content

        if len(content) > MAX_RENDERED_PDF_BYTES:
            raise ReportRenderError("Report renderer returned an oversized PDF")

        try:
            validate_pdf_bytes(content)
        except ReportStorageError as error:
            raise ReportRenderError(
                "Report renderer returned invalid PDF bytes"
            ) from error

        return content


def build_report_renderer() -> ReportRenderer:
    return HTTPReportRenderer(
        base_url=getattr(
            settings,
            "REPORT_RENDERER_URL",
            "",
        ),
        timeout_seconds=float(
            getattr(
                settings,
                "REPORT_RENDERER_TIMEOUT_SECONDS",
                70,
            )
        ),
    )
