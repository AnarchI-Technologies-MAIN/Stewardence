from __future__ import annotations

import uuid

import httpx
import pytest

from apps.jobs.handlers import build_job_handler_resolver
from apps.jobs.models import BackgroundJob
from apps.jobs.queue import ClaimedJob
from apps.reports.jobs import (
    ReportGenerationHandler,
    ReportGenerationJobError,
)
from apps.reports.models import ReportArtifact
from apps.reports.render_client import (
    HTTPReportRenderer,
    ReportRenderError,
)
from apps.reports.services import create_report
from apps.reports.storage import (
    LocalPrivateReportStorage,
    ReportStorageError,
    S3PrivateReportStorage,
    build_pdf_object_key,
)

pytestmark = pytest.mark.django_db(transaction=True)


class RecordingRenderer:
    def __init__(self, pdf_bytes=b"%PDF-1.7\nworker\n%%EOF\n"):
        self.pdf_bytes = pdf_bytes
        self.contexts = []

    def render(self, report_context):
        self.contexts.append(report_context)
        return self.pdf_bytes


def claimed_report_job(organization, report):
    return ClaimedJob(
        id=uuid.uuid4(),
        organization_id=organization.id,
        job_type=BackgroundJob.Type.REPORT_GENERATION,
        payload={"report_id": str(report.id)},
        attempts=1,
        claim_token=uuid.uuid4(),
    )


def create_fixture_report(report_context):
    user, organization, _membership, _item, snapshot = report_context
    report = create_report(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )
    return organization, report


def test_report_generation_handler_materializes_private_artifact(
    report_context,
    tmp_path,
):
    organization, report = create_fixture_report(report_context)
    renderer = RecordingRenderer()
    storage = LocalPrivateReportStorage(tmp_path)

    handler = ReportGenerationHandler(
        renderer=renderer,
        storage=storage,
    )
    job = claimed_report_job(organization, report)

    prepared = handler.prepare(job)

    heartbeats = []
    result = handler.execute_external(
        prepared,
        lambda: heartbeats.append("heartbeat"),
    )
    artifact = handler.persist(job, result)

    assert heartbeats == ["heartbeat", "heartbeat"]
    assert len(renderer.contexts) == 1
    assert renderer.contexts[0]["metadata"]["report_identifier"] == (
        report.report_identifier
    )

    assert artifact.report_id == report.id
    assert artifact.organization_id == organization.id
    assert artifact.assessment_snapshot_id == report.assessment_snapshot_id
    assert artifact.content_type == "application/pdf"
    assert artifact.size_bytes == len(renderer.pdf_bytes)

    expected_key = build_pdf_object_key(
        organization_id=organization.id,
        assessment_snapshot_id=report.assessment_snapshot_id,
        report_id=report.id,
    )

    assert artifact.object_key == expected_key
    assert storage.get(key=expected_key) == renderer.pdf_bytes


def test_report_generation_persistence_is_idempotent(
    report_context,
    tmp_path,
):
    organization, report = create_fixture_report(report_context)
    renderer = RecordingRenderer()
    storage = LocalPrivateReportStorage(tmp_path)

    handler = ReportGenerationHandler(
        renderer=renderer,
        storage=storage,
    )
    job = claimed_report_job(organization, report)

    prepared = handler.prepare(job)
    result = handler.execute_external(prepared, lambda: None)

    first = handler.persist(job, result)
    second = handler.persist(job, result)

    assert first.id == second.id
    assert ReportArtifact.objects.filter(report=report).count() == 1


def test_report_generation_rejects_payload_expansion(
    report_context,
    tmp_path,
):
    organization, report = create_fixture_report(report_context)

    handler = ReportGenerationHandler(
        renderer=RecordingRenderer(),
        storage=LocalPrivateReportStorage(tmp_path),
    )

    job = claimed_report_job(organization, report)
    expanded_job = ClaimedJob(
        id=job.id,
        organization_id=job.organization_id,
        job_type=job.job_type,
        payload={
            "report_id": str(report.id),
            "output_path": "/forbidden/report.pdf",
        },
        attempts=job.attempts,
        claim_token=job.claim_token,
    )

    with pytest.raises(
        ReportGenerationJobError,
        match="only report_id",
    ):
        handler.prepare(expanded_job)


def test_report_handler_resolver_registers_report_generation(
    report_context,
    tmp_path,
):
    renderer = RecordingRenderer()
    storage = LocalPrivateReportStorage(tmp_path)

    resolver = build_job_handler_resolver(
        report_renderer=renderer,
        report_storage=storage,
    )

    handler = resolver(BackgroundJob.Type.REPORT_GENERATION)

    assert isinstance(handler, ReportGenerationHandler)
    assert handler.renderer is renderer
    assert handler.storage is storage


def test_http_renderer_accepts_only_pdf_response():
    def handle(request):
        assert request.url.path == "/v1/render"
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=b"%PDF-1.7\nrender-client\n%%EOF\n",
        )

    renderer = HTTPReportRenderer(
        base_url="http://renderer.test",
        transport=httpx.MockTransport(handle),
    )

    content = renderer.render({"payload": "test"})

    assert content.startswith(b"%PDF-")


def test_http_renderer_rejects_non_pdf_content_type():
    def handle(_request):
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"%PDF-1.7\nfake\n%%EOF\n",
        )

    renderer = HTTPReportRenderer(
        base_url="http://renderer.test",
        transport=httpx.MockTransport(handle),
    )

    with pytest.raises(
        ReportRenderError,
        match="unexpected content type",
    ):
        renderer.render({"payload": "test"})


class FakeBody:
    def __init__(self, content):
        self.content = content

    def read(self):
        return self.content


class FakeS3Client:
    def __init__(self):
        self.objects = {}

    def get_object(self, *, Bucket, Key):
        identity = (Bucket, Key)

        if identity not in self.objects:
            error_response = {
                "Error": {
                    "Code": "NoSuchKey",
                    "Message": "missing",
                }
            }
            raise __import__("botocore.exceptions").exceptions.ClientError(
                error_response,
                "GetObject",
            )

        return {
            "Body": FakeBody(self.objects[identity]),
        }

    def put_object(self, *, Bucket, Key, Body, ContentType):
        assert ContentType == "application/pdf"
        self.objects[(Bucket, Key)] = Body

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


def s3_storage(client):
    return S3PrivateReportStorage(
        bucket_name="reports-test",
        endpoint_url="https://storage.example",
        access_key_id="test-key",
        secret_access_key="test-secret",
        region_name="auto",
        addressing_style="virtual",
        client=client,
    )


def test_s3_storage_round_trip_and_identical_retry():
    client = FakeS3Client()
    storage = s3_storage(client)

    content = b"%PDF-1.7\ns3\n%%EOF\n"

    storage.put(
        key="organizations/test/report.pdf",
        content=content,
        content_type="application/pdf",
    )
    storage.put(
        key="organizations/test/report.pdf",
        content=content,
        content_type="application/pdf",
    )

    assert storage.get(key="organizations/test/report.pdf") == content


def test_s3_storage_rejects_different_content_at_same_key():
    client = FakeS3Client()
    storage = s3_storage(client)

    storage.put(
        key="organizations/test/report.pdf",
        content=b"%PDF-1.7\nfirst\n%%EOF\n",
        content_type="application/pdf",
    )

    with pytest.raises(
        ReportStorageError,
        match="different content",
    ):
        storage.put(
            key="organizations/test/report.pdf",
            content=b"%PDF-1.7\nsecond\n%%EOF\n",
            content_type="application/pdf",
        )
