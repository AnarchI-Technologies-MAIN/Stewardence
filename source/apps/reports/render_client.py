from __future__ import annotations

import math
import re
from time import monotonic
from typing import Any, Protocol

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.jobs.recovery import ReplaySafeErrorWrapper, RetryableOperationError

from .storage import PDF_CONTENT_TYPE, ReportStorageError, validate_pdf_bytes

MAX_RENDERED_PDF_BYTES = 16 * 1_048_576
RENDER_READ_CHUNK_BYTES = 64 * 1024


class ReportRenderError(ReplaySafeErrorWrapper):
    pass


class TransientReportRenderError(ReportRenderError, RetryableOperationError):
    pass


class ReportRenderer(Protocol):
    def render(self, report_context: dict[str, Any]) -> bytes: ...


class HTTPReportRenderer:
    """Bound bytes and elapsed progress, without claiming strict cancellation.

    The monotonic budget is checked after headers and every raw transport chunk.
    A blocked transport read can overrun it by the configured inactivity timeout;
    transport-owned allocations and interrupted scheduler time are outside this
    cooperative boundary.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 70.0,
        transport=None,
    ):
        if not base_url:
            raise ImproperlyConfigured("REPORT_RENDERER_URL is required")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ImproperlyConfigured(
                "REPORT_RENDERER_TIMEOUT_SECONDS must be finite and positive"
            )

        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def render(self, report_context: dict[str, Any]) -> bytes:
        started = monotonic()

        def check_elapsed():
            if monotonic() - started >= self.timeout_seconds:
                raise TransientReportRenderError(
                    "Report renderer exceeded its elapsed response budget"
                )

        try:
            with (
                httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client,
                client.stream(
                    "POST",
                    f"{self.base_url}/v1/render",
                    json=report_context,
                    headers={"Accept": PDF_CONTENT_TYPE, "Accept-Encoding": "identity"},
                ) as response,
            ):
                # Reject status and representation headers before consuming body.
                if response.status_code in {408, 429, 502, 503, 504}:
                    raise TransientReportRenderError(
                        "Report renderer temporarily unavailable"
                    )
                if response.status_code != 200:
                    raise ReportRenderError(
                        f"Report renderer returned HTTP {response.status_code}"
                    )
                check_elapsed()
                content_type = (
                    response.headers.get("Content-Type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if content_type != PDF_CONTENT_TYPE:
                    raise ReportRenderError(
                        "Report renderer returned an unexpected content type"
                    )
                encodings = response.headers.get_list("Content-Encoding")
                if encodings and (
                    len(encodings) != 1 or encodings[0].strip().lower() != "identity"
                ):
                    raise ReportRenderError(
                        "Report renderer returned an unexpected content encoding"
                    )
                lengths = response.headers.get_list("Content-Length")
                declared_length = None
                if lengths:
                    if (
                        len(lengths) != 1
                        or len(lengths[0]) > 20
                        or re.fullmatch(r"[0-9]+", lengths[0].strip()) is None
                    ):
                        raise ReportRenderError(
                            "Report renderer returned an invalid content length"
                        )
                    declared_length = int(lengths[0])
                    if declared_length > MAX_RENDERED_PDF_BYTES:
                        raise ReportRenderError(
                            "Report renderer returned an oversized PDF"
                        )
                content = bytearray()
                # Do not aggregate tiny transport chunks before checking time.
                # Raw chunks never decompress a representation. Check bounds
                # before extending; transport-owned allocations are not ours.
                for chunk in response.iter_raw():
                    check_elapsed()
                    if len(content) + len(chunk) > MAX_RENDERED_PDF_BYTES:
                        raise ReportRenderError(
                            "Report renderer returned an oversized PDF"
                        )
                    content.extend(chunk)
                check_elapsed()
                if declared_length is not None and len(content) != declared_length:
                    raise ReportRenderError(
                        "Report renderer returned a mismatched content length"
                    )
        except httpx.HTTPError as error:
            raise ReportRenderError("Report renderer request failed") from error
        pdf = bytes(content)
        try:
            validate_pdf_bytes(pdf)
        except ReportStorageError as error:
            raise ReportRenderError(
                "Report renderer returned invalid PDF bytes"
            ) from error
        return pdf


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
