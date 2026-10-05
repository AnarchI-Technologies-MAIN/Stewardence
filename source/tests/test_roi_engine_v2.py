from dataclasses import replace
from decimal import Decimal

import pytest

from apps.roi.engine import Assumption, AssumptionProvenance, ROIInputs, calculate_roi as legacy
from apps.roi.engine_v2 import calculate_roi


def inputs():
    def declared(value):
        return Assumption(value, AssumptionProvenance.CUSTOMER_SUPPLIED)
    return ROIInputs(declared(100), declared(120), declared(12), declared(2),
                     declared(50), declared(0), declared(0))


@pytest.mark.parametrize("name", ["monthly_subscription_cost", "implementation_cost",
    "hours_saved_per_month", "loaded_hourly_rate", "attributable_revenue", "avoided_monthly_cost"])
def test_unknown_never_becomes_complete_roi(name):
    value = replace(inputs(), **{name: Assumption(0, AssumptionProvenance.UNKNOWN)})
    result = calculate_roi(value)
    assert result.monthly_net_value is None
    assert result.roi_percent is None
    assert result.unknown_inputs == (name,)
    assert result.roi_unavailable_reason == "Required assumptions are unknown"
    assert legacy(value).monthly_net_value is not None


def test_partial_result_retains_known_cost_and_negative_outcome():
    result = calculate_roi(inputs())
    assert result.monthly_total_cost == Decimal("110.00")
    assert result.monthly_net_value == Decimal("-10.00")
    assert result.roi_percent == Decimal("-9.09")
    partial = calculate_roi(replace(inputs(), hours_saved_per_month=Assumption(0, AssumptionProvenance.UNKNOWN)))
    assert partial.monthly_total_cost == Decimal("110.00")
    assert partial.monthly_value is None


def test_declared_zero_is_known_and_zero_denominator_is_explicit():
    value = replace(inputs(), monthly_subscription_cost=Assumption(0, AssumptionProvenance.MEASURED),
                    implementation_cost=Assumption(0, AssumptionProvenance.MEASURED))
    result = calculate_roi(value)
    assert result.monthly_net_value == Decimal("100.00")
    assert result.unknown_inputs == ()
    assert result.roi_percent is None
    assert result.roi_unavailable_reason == "Monthly total cost is zero"


def test_complete_inputs_preserve_legacy_rounding_at_each_step():
    value = replace(inputs(), attributable_revenue=Assumption(Decimal("0.005"), AssumptionProvenance.ESTIMATED),
                    avoided_monthly_cost=Assumption(Decimal("0.005"), AssumptionProvenance.ESTIMATED))
    old, new = legacy(value), calculate_roi(value)
    for name in ("monthly_labor_value", "monthly_value", "amortized_implementation_cost",
                 "monthly_total_cost", "monthly_net_value", "roi_percent", "arithmetic"):
        assert getattr(old, name) == getattr(new, name)


@pytest.mark.django_db
def test_unknown_snapshot_and_browser_report_preserve_nulls_and_legacy(client, report_context):
    from django.urls import reverse
    from apps.assessments.snapshots import create_assessment_snapshot, verify_snapshot
    from apps.reports.models import Report
    from apps.reports.context import build_report_context

    user, organization, _, item, original = report_context
    original_hash = original.result_sha256
    candidate = create_assessment_snapshot(
        organization_id=organization.id, created_by_id=user.id,
        assessed_item_id=item.id, captured_at=original.captured_at,
        roi_inputs=replace(inputs(), hours_saved_per_month=Assumption(0, AssumptionProvenance.UNKNOWN)),
        roi_engine_version="AL-ROI-2",
    )
    assert candidate.input_payload["engine_versions"]["roi"] == "AL-ROI-2"
    assert candidate.result_payload["roi"]["monthly_net_value"] is None
    assert candidate.result_payload["roi"]["monthly_total_cost"] == "110.00"
    assert verify_snapshot(candidate)
    response = client.post(reverse("reports:generate", args=(candidate.id,)))
    assert response.status_code == 302
    report = Report.objects.get(assessment_snapshot=candidate)
    context = build_report_context(report)
    assert context["executive_summary"]["monthly_net_value"] is None
    page = client.get(reverse("reports:detail", args=(report.id,)))
    assert page.status_code == 200
    assert b"Required assumptions are unknown" in page.content
    assert b"$None" not in page.content
    from renderer.template import render_report_html
    rendered = render_report_html(context)
    assert "Required assumptions are unknown" in rendered
    assert "$None" not in rendered
    original.refresh_from_db()
    assert original.result_sha256 == original_hash
    assert original.result_payload["roi"]["engine_version"] == "AL-ROI-1"
    assert verify_snapshot(original)


@pytest.mark.django_db
def test_actual_chromium_pdf_preserves_unknowns_and_known_cost(tmp_path,report_context):
    import os,subprocess
    if os.getenv('STEWARDENCE_REAL_PDF_QUALIFICATION')!='1':
        pytest.skip('Actual Chromium rendering requires the isolated qualification image')
    from apps.assessments.snapshots import create_assessment_snapshot
    from apps.reports.services import create_report
    from apps.reports.context import build_report_context
    from renderer.render import render_pdf
    user,org,_,item,original=report_context
    snapshot=create_assessment_snapshot(organization_id=org.id,created_by_id=user.id,
        assessed_item_id=item.id,captured_at=original.captured_at,
        roi_inputs=replace(inputs(),hours_saved_per_month=Assumption(0,AssumptionProvenance.UNKNOWN)),roi_engine_version='AL-ROI-2')
    report=create_report(organization_id=org.id,assessment_snapshot_id=snapshot.id,created_by_id=user.id)
    pdf=render_pdf(build_report_context(report),output_directory=tmp_path)
    assert pdf.startswith(b'%PDF-') and len(pdf)>1000
    text=subprocess.run(['pdftotext','-','-'],input=pdf,capture_output=True,check=True).stdout.decode()
    assert 'Required assumptions are unknown' in text
    assert '110.00' in text
    assert '$None' not in text
    import time
    time.sleep(1.1)
    replay=render_pdf(build_report_context(report),output_directory=tmp_path)
    assert replay==pdf
    from pathlib import Path
    evidence=Path('/qualification-evidence')
    if evidence.is_dir():
        (evidence/'roi-unknown.pdf').write_bytes(pdf)
        import json
        (evidence/'synthetic-render-payload.json').write_text(json.dumps(build_report_context(report)),encoding='utf-8')
