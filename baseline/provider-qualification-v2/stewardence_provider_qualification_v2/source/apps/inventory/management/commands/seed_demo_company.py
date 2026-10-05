from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.assessments.models import AssessmentSnapshot
from apps.assessments.snapshots import create_assessment_snapshot
from apps.audit.append import append_audit_event
from apps.audit.events import EVENT_INVENTORY_CREATED, EVENT_RULE_CREATED
from apps.inventory.models import InventoryItem
from apps.organizations.models import Organization, OrganizationMember
from apps.policies.models import OrganizationRule
from apps.reports.jobs import ensure_report_generation_job
from apps.reports.models import Report
from apps.reports.services import create_report
from apps.roi.engine import Assumption, AssumptionProvenance, ROIInputs

from .seed_demo_inventory import create_demo_inventory

EXPECTED_RISK_BANDS = {"Low", "Moderate", "High", "Critical"}
EXPECTED_FINDING_SEVERITIES = {"LOW", "MODERATE", "HIGH", "CRITICAL"}
WRITE_ROLES = {
    OrganizationMember.Role.OWNER,
    OrganizationMember.Role.ADMIN,
    OrganizationMember.Role.ASSESSOR,
}


def _uuid(value: str, *, name: str) -> UUID:
    try:
        return UUID(value)
    except (TypeError, ValueError) as error:
        raise CommandError(f"{name} must be a UUID") from error


def _assumption(value: Decimal | int) -> Assumption:
    return Assumption(
        value=value,
        provenance=AssumptionProvenance.CUSTOMER_SUPPLIED,
    )


def _roi_inputs(
    *,
    subscription: str,
    implementation: str,
    hours_saved: str,
    hourly_rate: str,
    revenue: str = "0.00",
    avoided_cost: str = "0.00",
) -> ROIInputs:
    return ROIInputs(
        monthly_subscription_cost=_assumption(Decimal(subscription)),
        implementation_cost=_assumption(Decimal(implementation)),
        implementation_amortization_months=_assumption(12),
        hours_saved_per_month=_assumption(Decimal(hours_saved)),
        loaded_hourly_rate=_assumption(Decimal(hourly_rate)),
        attributable_revenue=_assumption(Decimal(revenue)),
        avoided_monthly_cost=_assumption(Decimal(avoided_cost)),
    )


def _create_demo_rules(*, organization_id: UUID, actor_user_id: UUID):
    definitions = (
        {
            "name": "Review public-content assistants",
            "definition": {
                "all": [
                    {
                        "field": "data_categories",
                        "operator": "contains",
                        "value": "public_information",
                    },
                    {
                        "field": "capabilities",
                        "operator": "contains",
                        "value": "content_generation",
                    },
                ],
                "effects": [
                    {
                        "type": "create_finding",
                        "message": (
                            "Confirm staff review before public content is used."
                        ),
                    }
                ],
            },
            "result_on_match": OrganizationRule.Result.WARNING,
            "severity": OrganizationRule.Severity.LOW,
            "explanation": (
                "This office assistant drafts public content, and a person remains "
                "responsible for the final communication."
            ),
            "remediation": (
                "Keep the existing staff review step and record who approves the "
                "final communication."
            ),
        },
        {
            "name": "Review client-information analysis",
            "definition": {
                "all": [
                    {
                        "field": "data_categories",
                        "operator": "contains",
                        "value": "client_information",
                    },
                    {
                        "field": "capabilities",
                        "operator": "contains",
                        "value": "data_analysis",
                    },
                ],
                "effects": [
                    {"type": "severity_floor", "value": "MODERATE"},
                    {
                        "type": "recommend_review",
                        "message": "Confirm de-identification and staff review.",
                    },
                ],
            },
            "result_on_match": OrganizationRule.Result.WARNING,
            "severity": OrganizationRule.Severity.MODERATE,
            "explanation": (
                "This software analyzes client information, even though the demo "
                "workflow records de-identification and staff review."
            ),
            "remediation": (
                "Confirm the de-identification procedure and document the person "
                "who reviews each result."
            ),
        },
    )

    rules = []
    for values in definitions:
        rule = OrganizationRule.objects.create(
            organization_id=organization_id,
            created_by_id=actor_user_id,
            source_type=OrganizationRule.SourceType.MANUAL,
            enabled=True,
            **values,
        )
        append_audit_event(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=EVENT_RULE_CREATED,
            entity_type="organization_rule",
            entity_id=rule.id,
            data={"demo": True, "version": str(rule.version)},
        )
        rules.append(rule)
    return rules


def _assert_empty_demo_target() -> None:
    populated = {
        "inventory": InventoryItem.objects.exists(),
        "rules": OrganizationRule.objects.exists(),
        "assessments": AssessmentSnapshot.objects.exists(),
        "reports": Report.objects.exists(),
    }
    if any(populated.values()):
        names = ", ".join(name for name, exists in populated.items() if exists)
        raise CommandError(f"Demo company must start empty; found existing {names}")


def _risk_evidence(snapshot: AssessmentSnapshot) -> tuple[set[str], set[str]]:
    results = snapshot.result_payload["inventory_results"]
    bands = {result["risk"]["band"] for result in results}
    severities = {
        finding["severity"]
        for result in results
        for finding in result["policy_results"]
        if finding["result"] in {"FAIL", "WARNING"}
    }
    return bands, severities


class Command(BaseCommand):
    help = (
        "Seed the empty Demo Bookkeeping Company with manual inventory, "
        "two ROI assessments, and a queued polished report."
    )

    def add_arguments(self, parser):
        parser.add_argument("organization_id", type=str)
        parser.add_argument("actor_user_id", type=str)

    def handle(self, *args, **options):
        organization_id = _uuid(
            options["organization_id"],
            name="organization_id",
        )
        actor_user_id = _uuid(
            options["actor_user_id"],
            name="actor_user_id",
        )

        with identity_transaction(actor_user_id):
            with tenant_transaction(organization_id):
                membership = OrganizationMember.objects.filter(
                    organization_id=organization_id,
                    user_id=actor_user_id,
                ).first()
                if membership is None or membership.role not in WRITE_ROLES:
                    raise CommandError(
                        "The actor must be an owner, administrator, or assessor "
                        "in the demo company"
                    )

                organization = Organization.objects.get(id=organization_id)
                if organization.name != "Demo Bookkeeping Company":
                    raise CommandError(
                        "This command only seeds an organization named "
                        "Demo Bookkeeping Company"
                    )

                _assert_empty_demo_target()
                items = create_demo_inventory(organization)
                by_name = {item.display_name: item for item in items}

                for item in items:
                    append_audit_event(
                        organization_id=organization_id,
                        actor_user_id=actor_user_id,
                        event_type=EVENT_INVENTORY_CREATED,
                        entity_type="inventory_item",
                        entity_id=item.id,
                        data={"demo": True, "source_type": item.source_type},
                    )

                rules = _create_demo_rules(
                    organization_id=organization_id,
                    actor_user_id=actor_user_id,
                )
                captured_at = datetime.now(UTC)
                poor_roi = create_assessment_snapshot(
                    organization_id=organization_id,
                    created_by_id=actor_user_id,
                    assessed_item_id=by_name["Microsoft Copilot"].id,
                    roi_inputs=_roi_inputs(
                        subscription="240.00",
                        implementation="1200.00",
                        hours_saved="1.00",
                        hourly_rate="40.00",
                    ),
                    captured_at=captured_at,
                )
                strong_roi = create_assessment_snapshot(
                    organization_id=organization_id,
                    created_by_id=actor_user_id,
                    assessed_item_id=by_name["Zapier"].id,
                    roi_inputs=_roi_inputs(
                        subscription="120.00",
                        implementation="600.00",
                        hours_saved="18.00",
                        hourly_rate="50.00",
                        avoided_cost="100.00",
                    ),
                    captured_at=captured_at + timedelta(seconds=1),
                )

                bands, severities = _risk_evidence(strong_roi)
                if not EXPECTED_RISK_BANDS <= bands:
                    raise CommandError(
                        "Demo assessment does not contain all four risk bands"
                    )
                if not EXPECTED_FINDING_SEVERITIES <= severities:
                    raise CommandError(
                        "Demo assessment does not contain all four finding severities"
                    )

                report = create_report(
                    organization_id=organization_id,
                    assessment_snapshot_id=strong_roi.id,
                    created_by_id=actor_user_id,
                )
                job = ensure_report_generation_job(report=report)
                if job is None:
                    raise CommandError("The demo report generation job was not queued")

        self.stdout.write(
            json.dumps(
                {
                    "status": "CREATED",
                    "organization_id": str(organization_id),
                    "manual_inventory_count": len(items),
                    "unknown_item": "Unknown AI Tool",
                    "manual_rule_count": len(rules),
                    "poor_roi_assessment_id": str(poor_roi.id),
                    "poor_roi_percent": poor_roi.result_payload["roi"]["roi_percent"],
                    "strong_roi_assessment_id": str(strong_roi.id),
                    "strong_roi_percent": strong_roi.result_payload["roi"][
                        "roi_percent"
                    ],
                    "risk_bands": sorted(bands),
                    "finding_severities": sorted(severities),
                    "report_id": str(report.id),
                    "report_identifier": report.report_identifier,
                    "report_job_id": str(job.id),
                },
                indent=2,
                sort_keys=True,
            )
        )
