from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.urls import reverse

from apps.assessments.snapshots import create_assessment_snapshot
from apps.audit.models import AuditEvent
from apps.jobs.models import BackgroundJob
from apps.organizations.models import Organization, OrganizationMember
from apps.reports.context import (
    REPORT_CONTEXT_VERSION,
    REPORT_TITLE,
    build_report_context,
)
from apps.reports.models import Report
from apps.reports.services import create_report, format_report_identifier
from apps.roi.engine import Assumption, AssumptionProvenance, ROIInputs

pytestmark = pytest.mark.django_db


def assumption(value, provenance=AssumptionProvenance.CUSTOMER_SUPPLIED):
    return Assumption(Decimal(str(value)), provenance)


def roi_inputs():
    return ROIInputs(
        monthly_subscription_cost=assumption("100.00"),
        implementation_cost=assumption("1200.00"),
        implementation_amortization_months=Assumption(
            12,
            AssumptionProvenance.ESTIMATED,
        ),
        hours_saved_per_month=assumption(
            "10.00",
            AssumptionProvenance.MEASURED,
        ),
        loaded_hourly_rate=assumption("50.00"),
        attributable_revenue=assumption(
            "200.00",
            AssumptionProvenance.ESTIMATED,
        ),
        avoided_monthly_cost=assumption(
            "100.00",
            AssumptionProvenance.MEASURED,
        ),
    )


def test_report_identifier_uses_the_accepted_sequence_format():
    assert format_report_identifier(2026, 14) == "AL-2026-000014"


def test_report_generation_is_idempotent_and_audited(report_context):
    user, organization, _membership, _item, snapshot = report_context

    report = create_report(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )
    repeated = create_report(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )

    assert repeated.id == report.id
    assert re.fullmatch(
        rf"AL-{report.identifier_year:04d}-\d{{6,}}",
        report.report_identifier,
    )
    assert report.organization_display_name == "Report Firm"
    event = AuditEvent.objects.get(event_type="report.generated")
    assert event.entity_id == report.id
    assert event.data == {
        "assessment_snapshot_id": str(snapshot.id),
        "report_identifier": report.report_identifier,
    }


def test_report_identifiers_advance_in_sequence(report_context):
    user, organization, _membership, item, snapshot = report_context
    first = create_report(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )
    second_snapshot = create_assessment_snapshot(
        organization_id=organization.id,
        created_by_id=user.id,
        assessed_item_id=item.id,
        roi_inputs=roi_inputs(),
        captured_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        previous_snapshot=snapshot,
    )
    second = create_report(
        organization_id=organization.id,
        assessment_snapshot_id=second_snapshot.id,
        created_by_id=user.id,
    )

    assert second.sequence == first.sequence + 1
    assert second.report_identifier == format_report_identifier(
        second.identifier_year,
        second.sequence,
    )


def test_canonical_context_contains_every_required_report_section(
    report_context,
):
    user, organization, _membership, item, snapshot = report_context
    report = create_report(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )

    context = build_report_context(report)

    assert context["context_version"] == REPORT_CONTEXT_VERSION
    assert context["title"] == REPORT_TITLE
    assert {
        "executive_summary",
        "inventory",
        "risk_overview",
        "individual_risk_findings",
        "policy_findings",
        "recommendations",
        "ai_expenditure",
        "roi",
        "methodology",
        "evidence",
        "assessment_date",
        "ruleset_versions",
        "metadata",
    } <= context.keys()
    assert context["inventory"][0]["id"] == str(item.id)
    assert context["risk_overview"]["highest_individual_risk"] == {
        "score": 75,
        "band": "Critical",
        "tool_name": "Payroll Assistant",
    }
    assert context["ai_expenditure"]["monthly_total"] == "100.00"
    assert context["roi"]["result"]["roi_percent"] == "300.00"
    assert context["evidence"] == [
        {
            "provenance": "Declared",
            "reference": "EVIDENCE-1",
            "type": "customer_statement",
        }
    ]

    item.display_name = "Changed after assessment"
    item.monthly_cost_cents = 999999
    item.save(update_fields=("display_name", "monthly_cost_cents"))
    organization.name = "Renamed after report"
    organization.save(update_fields=("name",))

    assert build_report_context(report) == context


def test_browser_report_uses_canonical_context_and_safe_claims(
    client,
    report_context,
):
    _user, _organization, _membership, _item, snapshot = report_context

    response = client.post(reverse("reports:generate", args=(snapshot.id,)))

    assert response.status_code == 302
    report = Report.objects.get()
    assert response.url == reverse("reports:detail", args=(report.id,))

    generation_job = BackgroundJob.objects.get(
        organization_id=report.organization_id,
        job_type=BackgroundJob.Type.REPORT_GENERATION,
    )
    assert generation_job.status == BackgroundJob.Status.QUEUED
    assert generation_job.payload == {
        "report_id": str(report.id),
    }

    page = client.get(response.url)
    assert page.status_code == 200
    assert page.context["report"] == build_report_context(report)
    for text in (
        b"AI Risk &amp; ROI Assessment",
        b"Executive summary",
        b"AI and software inventory",
        b"Overall risk overview",
        b"Individual tool risk",
        b"Failed and warning policy findings",
        b"Recommendations",
        b"AI and software expenditure",
        b"Return on investment",
        b"Methodology",
        b"Evidence sources",
        b"Assessment and report metadata",
        report.report_identifier.encode(),
    ):
        assert text in page.content

    lowered = page.content.lower()
    assert b"certified compliant" not in lowered
    assert b"guaranteed secure" not in lowered


def test_repeated_report_generation_reuses_one_active_generation_job(
    client,
    report_context,
):
    _user, organization, _membership, _item, snapshot = report_context
    generate_url = reverse("reports:generate", args=(snapshot.id,))

    first = client.post(generate_url)
    second = client.post(generate_url)

    assert first.status_code == 302
    assert second.status_code == 302

    report = Report.objects.get(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
    )

    assert first.url == reverse("reports:detail", args=(report.id,))
    assert second.url == first.url

    generation_jobs = BackgroundJob.objects.filter(
        organization_id=organization.id,
        job_type=BackgroundJob.Type.REPORT_GENERATION,
        payload={"report_id": str(report.id)},
        status__in=(
            BackgroundJob.Status.QUEUED,
            BackgroundJob.Status.RUNNING,
        ),
    )

    assert generation_jobs.count() == 1


def test_report_routes_are_tenant_scoped_and_generation_is_post_only(
    client,
    report_context,
):
    user, organization, membership, _item, snapshot = report_context
    generate_url = reverse("reports:generate", args=(snapshot.id,))

    assert client.get(generate_url).status_code == 405

    membership.role = OrganizationMember.Role.VIEWER
    membership.save(update_fields=("role",))
    assert client.post(generate_url).status_code == 403
    assert Report.objects.count() == 0

    membership.role = OrganizationMember.Role.OWNER
    membership.save(update_fields=("role",))
    report = create_report(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )
    other_organization = Organization.objects.create(name="Other Firm")
    OrganizationMember.objects.create(
        user=user,
        organization=other_organization,
        role=OrganizationMember.Role.OWNER,
    )
    session = client.session
    session["active_organization_id"] = str(other_organization.id)
    session.save()

    response = client.get(
        reverse(
            "reports:detail",
            args=(report.id,),
        )
    )

    assert response.status_code == 302
    assert response.url == reverse(
        "organizations:workspace-selection"
    )
    assert "active_organization_id" not in client.session


def test_report_identity_model_rejects_instance_mutation(report_context):
    user, organization, _membership, _item, snapshot = report_context
    report = create_report(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )
    report.organization_display_name = "Changed"

    with pytest.raises(ValidationError, match="immutable"):
        report.save()

    with pytest.raises(DatabaseError, match="immutable"):
        Report.objects.filter(id=report.id).update(organization_display_name="Changed")


def test_report_and_audit_event_creation_are_atomic(
    report_context,
    monkeypatch,
):
    user, organization, _membership, _item, snapshot = report_context

    def fail_append(**_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(
        "apps.reports.services.append_audit_event",
        fail_append,
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        create_report(
            organization_id=organization.id,
            assessment_snapshot_id=snapshot.id,
            created_by_id=user.id,
        )

    assert Report.objects.count() == 0
    assert not AuditEvent.objects.filter(event_type="report.generated").exists()
