from __future__ import annotations

import json
import re
import threading
from http import HTTPStatus
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from renderer.render import (
    RenderFailure,
    RenderTimeout,
    render_pdf,
    render_pdf_with_hard_timeout,
)
from renderer.schema import (
    MAX_PAYLOAD_BYTES,
    InvalidReportRenderPayload,
    validate_report_render_payload,
)
from renderer.server import RendererRequestHandler
from renderer.template import render_report_html


def valid_payload() -> dict:
    assessment_id = str(uuid4())
    snapshot_id = str(uuid4())
    digest = "a" * 64
    return {
        "context_version": "AL-REPORT-CONTEXT-2",
        "title": "AI Risk & ROI Assessment",
        "metadata": {
            "report_identifier": "AL-2026-000014",
            "organization_display_name": "Example Firm",
            "assessment_date": "2026-09-04T12:00:00Z",
            "assessment_id": assessment_id,
            "assessment_version": 1,
            "assessment_snapshot_id": snapshot_id,
            "input_sha256": digest,
            "result_sha256": digest,
        },
        "executive_summary": {
            "inventory_count": 0,
            "highest_individual_risk": None,
            "monthly_spend": "0.00",
            "monthly_net_value": "0.00",
            "finding_count": 0,
        },
        "inventory": [],
        "risk_overview": {
            "highest_individual_risk": None,
            "counts_by_band": {"Low": 0, "Moderate": 0, "High": 0, "Critical": 0},
        },
        "individual_risk_findings": [],
        "policy_findings": [],
        "recommendations": [],
        "ai_expenditure": {"monthly_total": "0.00", "items": []},
        "roi": {
            "assessed_item_id": None,
            "assumptions": {},
            "result": {
                "monthly_value": "0.00",
                "monthly_total_cost": "0.00",
                "monthly_net_value": "0.00",
                "roi_percent": None,
                "arithmetic": [],
            },
        },
        "methodology": {
            "summary": "Deterministic assessment.",
            "snapshot_schema_version": "AL-ASSESSMENT-SNAPSHOT-1",
            "report_context_version": "AL-REPORT-CONTEXT-2",
            "engine_versions": {},
            "risk_configuration": {},
        },
        "evidence": [],
        "assessment_date": "2026-09-04T12:00:00Z",
        "ruleset_versions": {
            "platform": "1.0.0",
            "industry": {"name": "bookkeeping", "version": "1.0.0"},
            "organization": [],
        },
    }


@pytest.fixture
def renderer_http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), RendererRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request_renderer(server, method, path, body=None, headers=None):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    result = response.status, dict(response.headers), response.read()
    connection.close()
    return result


def test_renderer_accepts_only_the_canonical_structured_payload():
    payload = valid_payload()
    assert validate_report_render_payload(payload) is payload

    for forbidden in ("html", "css", "javascript", "output_path", "path"):
        changed = valid_payload()
        changed[forbidden] = "customer controlled"
        with pytest.raises(InvalidReportRenderPayload):
            validate_report_render_payload(changed)


@pytest.mark.parametrize("field", ["src", "url", "file", "href", "script"])
def test_renderer_rejects_nested_active_content_and_location_fields(field):
    payload = valid_payload()
    payload["evidence"] = [{"type": "test", field: "file:///etc/passwd"}]
    with pytest.raises(InvalidReportRenderPayload, match="Forbidden payload field"):
        validate_report_render_payload(payload)


def test_renderer_rejects_oversized_payload():
    payload = valid_payload()
    payload["metadata"]["organization_display_name"] = "x" * MAX_PAYLOAD_BYTES
    with pytest.raises(InvalidReportRenderPayload, match="too large"):
        validate_report_render_payload(payload)


def test_customer_strings_are_escaped_and_inert():
    payload = valid_payload()
    payload["metadata"]["organization_display_name"] = (
        '<script>fetch("https://example.invalid")</script>'
        '<img src="file:///etc/passwd">'
    )
    html = render_report_html(payload)

    assert "<script>" not in html
    assert '<img src="file:' not in html
    assert '<img class="brand-logo" src="data:image/png;base64,' in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=&quot;file:///etc/passwd&quot;&gt;" in html


def test_container_sandbox_controls_and_generated_output_path(monkeypatch):
    page = Mock()
    context = Mock()
    browser = Mock()
    chromium = Mock()
    playwright = Mock(chromium=chromium)
    manager = Mock()
    manager.__enter__ = Mock(return_value=playwright)
    manager.__exit__ = Mock(return_value=False)
    chromium.launch.return_value = browser
    browser.new_context.return_value = context
    context.new_page.return_value = page

    def write_pdf(*, path, **_kwargs):
        Path(path).write_bytes(b"%PDF-1.7\nsecure specimen")

    page.pdf.side_effect = write_pdf
    monkeypatch.setattr("renderer.render.sync_playwright", lambda: manager)

    output_directory = Path.cwd()
    rendered = render_pdf(valid_payload(), output_directory=output_directory)

    assert rendered.startswith(b"%PDF-")
    chromium.launch.assert_called_once_with(
        headless=True,
        chromium_sandbox=False,
    )
    browser.new_context.assert_called_once_with(
        java_script_enabled=False,
        service_workers="block",
    )
    pattern, abort = context.route.call_args.args
    assert pattern == "**/*"
    route = Mock()
    abort(route)
    route.abort.assert_called_once_with()
    output_path = Path(page.pdf.call_args.kwargs["path"])
    assert output_path.parent == output_directory
    assert re.fullmatch(r"report-[A-Za-z0-9_-]+\.pdf", output_path.name)
    assert not output_path.exists()


def test_renderer_compose_boundary_has_no_public_port_or_secrets():
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    renderer = compose.split("  renderer:", 1)[1].split("\nnetworks:", 1)[0]
    assert "ports:" not in renderer
    assert "environment:" not in renderer
    for control in (
        'user: "10001:10001"',
        "read_only: true",
        "cap_drop:",
        "- ALL",
        "no-new-privileges:true",
        "seccomp:./deploy/playwright-seccomp.json",
        "pids_limit: 256",
        "mem_limit: 768m",
        "cpus: 1.0",
    ):
        assert control in renderer
    assert "internal: true" in compose
    assert not any(
        secret in renderer.casefold()
        for secret in ("database_url", "oauth", "kek", "bucket", "aws_secret")
    )


def test_renderer_image_is_non_root_and_never_disables_the_sandbox():
    dockerfile = Path("Dockerfile.renderer").read_text(encoding="utf-8")
    assert "--uid 10001" in dockerfile
    assert "USER renderer" in dockerfile
    assert "--no-sandbox" not in dockerfile
    assert "--disable-setuid-sandbox" not in dockerfile


def test_render_timeout_terminates_the_isolated_process(monkeypatch):
    parent_connection = Mock()
    child_connection = Mock()
    process = Mock()
    parent_connection.poll.return_value = False
    process.is_alive.side_effect = (True, False)
    context = Mock()
    context.Pipe.return_value = (parent_connection, child_connection)
    context.Process.return_value = process
    monkeypatch.setattr("renderer.render.get_context", lambda _method: context)

    with pytest.raises(RenderTimeout):
        render_pdf_with_hard_timeout(valid_payload(), timeout_seconds=1)

    process.start.assert_called_once_with()
    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    parent_connection.close.assert_called_once_with()


def test_seccomp_profile_permits_namespaces_without_sys_admin():
    profile = json.loads(
        Path("deploy/playwright-seccomp.json").read_text(encoding="utf-8")
    )
    namespace_rule = profile["syscalls"][0]
    assert namespace_rule["action"] == "SCMP_ACT_ALLOW"
    assert {"clone", "setns", "unshare"} <= set(namespace_rule["names"])
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
    assert "CAP_SYS_ADMIN" in json.dumps(profile)


def test_renderer_http_health_and_fixed_render_endpoint(
    renderer_http_server,
    monkeypatch,
):
    expected_pdf = b"%PDF-1.7\nresult"
    render = Mock(return_value=expected_pdf)
    monkeypatch.setattr("renderer.server.render_pdf_with_hard_timeout", render)

    status, headers, body = request_renderer(renderer_http_server, "GET", "/healthz")
    assert status == HTTPStatus.OK
    assert headers["Cache-Control"] == "no-store"
    assert json.loads(body) == {"status": "ok"}

    payload = valid_payload()
    status, headers, body = request_renderer(
        renderer_http_server,
        "POST",
        "/v1/render",
        json.dumps(payload).encode(),
        {"Content-Type": "application/json"},
    )
    assert status == HTTPStatus.OK
    assert headers["Content-Type"] == "application/pdf"
    assert body == expected_pdf
    render.assert_called_once_with(payload)


def test_renderer_http_fails_closed_for_unknown_and_invalid_requests(
    renderer_http_server,
):
    assert request_renderer(renderer_http_server, "GET", "/unknown")[0] == 404
    assert request_renderer(renderer_http_server, "POST", "/unknown", b"{}")[0] == 404
    assert (
        request_renderer(renderer_http_server, "POST", "/v1/render", b'{"x":}')[0]
        == 422
    )
    assert (
        request_renderer(
            renderer_http_server,
            "POST",
            "/v1/render",
            b"{}",
            {"Transfer-Encoding": "chunked"},
        )[0]
        == 400
    )


def test_renderer_http_returns_retryable_failure_without_details(
    renderer_http_server,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        "renderer.server.render_pdf_with_hard_timeout",
        Mock(side_effect=RenderFailure("internal detail")),
    )
    status, _headers, body = request_renderer(
        renderer_http_server,
        "POST",
        "/v1/render",
        json.dumps(valid_payload()).encode(),
    )
    assert status == HTTPStatus.SERVICE_UNAVAILABLE
    assert b"internal detail" not in body
    assert "render_failed:internal detail" in capsys.readouterr().err
