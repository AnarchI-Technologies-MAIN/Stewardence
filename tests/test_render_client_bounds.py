"""Offline lazy transport proof; no provider calls or production attack claim."""

import httpx
import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.jobs.recovery import permits_retry
from apps.reports import render_client
from apps.reports.render_client import (
    MAX_RENDERED_PDF_BYTES,
    RENDER_READ_CHUNK_BYTES,
    HTTPReportRenderer,
    ReportRenderError,
    TransientReportRenderError,
)


class LazyBody(httpx.SyncByteStream):
    def __init__(self, size, *, failure=None):
        self.size = size
        self.failure = failure
        self.yielded = 0
        self.closed = False

    def __iter__(self):
        while self.yielded < self.size:
            count = min(RENDER_READ_CHUNK_BYTES, self.size - self.yielded)
            chunk = b"x" * count
            if self.yielded == 0 and count >= 5:
                chunk = b"%PDF-" + chunk[5:]
            self.yielded += count
            yield chunk
        if self.failure is not None:
            raise self.failure

    def close(self):
        self.closed = True


def renderer(body, *, status=200, headers=None):
    def respond(request):
        assert request.headers["Accept-Encoding"] == "identity"
        assert request.headers["Accept"] == "application/pdf"
        return httpx.Response(
            status,
            headers=headers or {"Content-Type": "application/pdf"},
            stream=body,
        )

    return HTTPReportRenderer(
        base_url="https://renderer.invalid", transport=httpx.MockTransport(respond)
    )


@pytest.mark.parametrize("declared", [None, "1", str(MAX_RENDERED_PDF_BYTES)])
def test_oversized_lazy_body_stops_before_unbounded_tail(declared):
    body = LazyBody(MAX_RENDERED_PDF_BYTES * 100)
    headers = {"Content-Type": "application/pdf"}
    if declared is not None:
        headers["Content-Length"] = declared
    with pytest.raises(ReportRenderError, match="oversized") as caught:
        renderer(body, headers=headers).render({})
    assert body.yielded == MAX_RENDERED_PDF_BYTES + RENDER_READ_CHUNK_BYTES
    assert body.closed
    assert not permits_retry(caught.value)


@pytest.mark.parametrize("size", [MAX_RENDERED_PDF_BYTES - 1, MAX_RENDERED_PDF_BYTES])
@pytest.mark.parametrize("declared", [False, True])
def test_exact_size_boundary_preserves_pdf_bytes(size, declared):
    body = LazyBody(size)
    headers = {"Content-Type": "application/pdf; charset=binary"}
    if declared:
        headers["Content-Length"] = str(size)
    result = renderer(body, headers=headers).render({})
    assert len(result) == size
    assert result.startswith(b"%PDF-")
    assert body.yielded == size
    assert body.closed


@pytest.mark.parametrize("status", [408, 429, 502, 503, 504])
def test_transient_status_consumes_no_body_and_keeps_retry_policy(status):
    body = LazyBody(MAX_RENDERED_PDF_BYTES * 100)
    with pytest.raises(TransientReportRenderError) as caught:
        renderer(body, status=status).render({})
    assert body.yielded == 0
    assert body.closed
    assert permits_retry(caught.value)


@pytest.mark.parametrize(
    "headers,message",
    [
        ({"Content-Type": "text/html"}, "content type"),
        ({"Content-Type": "application/pdf", "Content-Encoding": "gzip"}, "encoding"),
        ({"Content-Type": "application/pdf", "Content-Encoding": "br"}, "encoding"),
        ({"Content-Type": "application/pdf", "Content-Encoding": ""}, "encoding"),
        (
            {"Content-Type": "application/pdf", "Content-Encoding": "identity,gzip"},
            "encoding",
        ),
        (
            {"Content-Type": "application/pdf", "Content-Length": "16777217"},
            "oversized",
        ),
        ({"Content-Type": "application/pdf", "Content-Length": "-1"}, "length"),
        ({"Content-Type": "application/pdf", "Content-Length": "1,1"}, "length"),
        ({"Content-Type": "application/pdf", "Content-Length": "1.0"}, "length"),
    ],
)
def test_invalid_headers_close_without_consuming_representation(headers, message):
    body = LazyBody(MAX_RENDERED_PDF_BYTES * 100)
    with pytest.raises(ReportRenderError, match=message) as caught:
        renderer(body, headers=headers).render({})
    assert body.yielded == 0
    assert body.closed
    assert not permits_retry(caught.value)


@pytest.mark.parametrize("length", ["9", "11"])
def test_bounded_wrong_declared_length_is_not_success(length):
    body = LazyBody(10)
    with pytest.raises(ReportRenderError, match="mismatched content length"):
        renderer(
            body, headers={"Content-Type": "application/pdf", "Content-Length": length}
        ).render({})
    assert body.yielded == 10
    assert body.closed


@pytest.mark.parametrize(
    "failure,retry",
    [
        (httpx.ReadError("partial body"), True),
        (httpx.RemoteProtocolError("truncated"), False),
    ],
)
def test_partial_stream_failure_preserves_original_cause_and_closed_retry_graph(
    failure, retry
):
    body = LazyBody(RENDER_READ_CHUNK_BYTES, failure=failure)
    with pytest.raises(ReportRenderError, match="request failed") as caught:
        renderer(body).render({})
    assert caught.value.__cause__ is failure
    assert body.yielded == RENDER_READ_CHUNK_BYTES
    assert body.closed
    assert permits_retry(caught.value) is retry


def test_permanent_status_never_reads_body():
    body = LazyBody(1_000_000)
    with pytest.raises(ReportRenderError, match="HTTP 400") as caught:
        renderer(body, status=400).render({})
    assert body.closed and body.yielded == 0
    assert not permits_retry(caught.value)


def test_identity_encoding_does_not_relax_pdf_signature_validation():
    body = httpx.ByteStream(b"html document")
    with pytest.raises(ReportRenderError, match="invalid PDF"):
        renderer(
            body,
            headers={"Content-Type": "application/pdf", "Content-Encoding": "identity"},
        ).render({})


@pytest.mark.parametrize(
    "name,value", [("Content-Length", "10"), ("Content-Encoding", "identity")]
)
def test_duplicate_representation_headers_are_not_ambiguous_admission(name, value):
    body = LazyBody(10)
    headers = [("Content-Type", "application/pdf"), (name, value), (name, value)]
    with pytest.raises(ReportRenderError):
        renderer(body, headers=headers).render({})
    assert body.yielded == 0
    assert body.closed


def test_elapsed_headers_close_before_body(monkeypatch):
    clock = iter([100.0, 170.0])
    monkeypatch.setattr(render_client, "monotonic", lambda: next(clock))
    body = LazyBody(100)
    with pytest.raises(TransientReportRenderError, match="elapsed") as caught:
        renderer(body).render({})
    assert body.yielded == 0
    assert body.closed
    assert permits_retry(caught.value)


def test_slow_trickle_checks_each_raw_chunk_without_aggregation(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(render_client, "monotonic", lambda: now[0])

    class Trickle(httpx.SyncByteStream):
        yielded = 0
        closed = False

        def __iter__(self):
            for chunk in [b"%PDF-", b"x", b"y", b"unconsumed tail"]:
                now[0] += 25.0
                self.yielded += 1
                yield chunk

        def close(self):
            self.closed = True

    body = Trickle()
    with pytest.raises(TransientReportRenderError, match="elapsed") as caught:
        renderer(body).render({})
    assert body.yielded == 3
    assert body.closed
    assert permits_retry(caught.value)


def test_oversized_single_raw_chunk_is_rejected_before_buffer_extend():
    class LargeChunk(httpx.SyncByteStream):
        yielded = 0
        closed = False

        def __iter__(self):
            self.yielded += 1
            yield b"%PDF-" + b"x" * MAX_RENDERED_PDF_BYTES
            self.yielded += 1
            yield b"unconsumed tail"

        def close(self):
            self.closed = True

    body = LargeChunk()
    with pytest.raises(ReportRenderError, match="oversized"):
        renderer(body).render({})
    assert body.yielded == 1
    assert body.closed


def test_delayed_eof_is_checked_before_accepting_pdf(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(render_client, "monotonic", lambda: now[0])

    class LateEOF(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            yield b"%PDF-1.7\n"
            now[0] = 170.0

        def close(self):
            self.closed = True

    body = LateEOF()
    with pytest.raises(TransientReportRenderError, match="elapsed") as caught:
        renderer(body).render({})
    assert body.closed
    assert permits_retry(caught.value)


@pytest.mark.parametrize(
    "timeout", [0, -1, float("nan"), float("inf"), -float("inf"), True, None, "70"]
)
def test_nonfinite_or_nonpositive_timeout_is_configuration_failure(timeout):
    with pytest.raises(ImproperlyConfigured, match="finite and positive"):
        HTTPReportRenderer(base_url="https://renderer.invalid", timeout_seconds=timeout)
