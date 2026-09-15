from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.inventory.models import InventoryItem
from apps.organizations.models import Organization, OrganizationMember
from apps.policies.engine import PolicyDefinitionError, PolicyResult
from apps.policies.models import OrganizationRule
from apps.policies.organization_rules import compile_organization_rule
from tests.conftest import grant_core_entitlement

pytestmark = pytest.mark.django_db


@pytest.fixture
def rule_context(client):
    user = get_user_model().objects.create_user("rules@example.com")
    organization = Organization.objects.create(name="Rules Firm")
    membership = OrganizationMember.objects.create(
        user=user,
        organization=organization,
        role=OrganizationMember.Role.OWNER,
    )
    item = InventoryItem.objects.create(
        organization=organization,
        display_name="Payroll Messenger",
        vendor_name="Example Vendor",
        data_categories=["payroll"],
        capabilities=["external_transfer"],
        human_approval=False,
    )
    grant_core_entitlement(user, organization)
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(organization.id)
    session.save()
    return user, organization, membership, item


def rule_payload(item, **overrides):
    payload = {
        "action": "save",
        "name": "Payroll transfer approval",
        "data_category": "payroll",
        "capability": "external_transfer",
        "severity_floor": "HIGH",
        "required_control": "human_approval",
        "risk_dimension": "data_sensitivity",
        "risk_points": "25",
        "finding_message": "Review payroll transfers.",
        "review_message": "Confirm the approval procedure.",
        "result_on_match": "FAIL",
        "severity": "HIGH",
        "explanation": (
            "Payroll information can leave the firm through this software."
        ),
        "remediation": "Require a person to approve each payroll transfer.",
        "enabled": "on",
        "test_item": str(item.id),
    }
    payload.update(overrides)
    return payload


def create_rule(client, item, **overrides):
    response = client.post(reverse("policies:create"), rule_payload(item, **overrides))
    assert response.status_code == 302
    return OrganizationRule.objects.get()


def test_sentence_builder_creates_the_payroll_approval_and_high_floor_example(
    client, rule_context
):
    _user, organization, _membership, item = rule_context
    page = client.get(reverse("policies:create"))

    assert page.status_code == 200
    assert b"No-code rule builder" in page.content
    assert b"This software accesses" in page.content
    assert b"This software can" in page.content
    assert b"Minimum risk level" in page.content
    assert b"Require this control" in page.content

    rule = create_rule(client, item)

    assert rule.organization == organization
    assert rule.version == 1
    assert rule.definition["all"] == [
        {"field": "data_categories", "operator": "contains", "value": "payroll"},
        {
            "field": "capabilities",
            "operator": "contains",
            "value": "external_transfer",
        },
    ]
    assert {effect["type"] for effect in rule.definition["effects"]} == {
        "risk_points",
        "severity_floor",
        "require_control",
        "create_finding",
        "recommend_review",
    }
    compiled = compile_organization_rule(rule)
    assert compiled.result_on_match is PolicyResult.FAIL
    assert {effect.type for effect in compiled.effects} == {
        "risk_points",
        "severity_floor",
        "require_control",
        "create_finding",
        "recommend_review",
    }


def test_rule_test_is_posted_without_saving_and_explains_the_result(
    client, rule_context
):
    _user, _organization, _membership, item = rule_context
    payload = rule_payload(item, action="test")

    response = client.post(reverse("policies:create"), payload)

    assert response.status_code == 200
    assert OrganizationRule.objects.count() == 0
    assert b"Test result: Fail" in response.content
    assert b"Payroll information can leave the firm" in response.content
    assert b"Require a person to approve" in response.content


def test_detail_explains_rule_and_hides_structured_json_in_details(
    client, rule_context
):
    _user, _organization, _membership, item = rule_context
    rule = create_rule(client, item)

    response = client.get(reverse("policies:detail", args=(rule.id,)))

    assert response.status_code == 200
    assert b"What this rule means" in response.content
    assert b"View technical details" in response.content
    assert b"&quot;operator&quot;: &quot;contains&quot;" in response.content
    assert b"eval(" not in response.content
    assert b"exec(" not in response.content
    assert b"javascript" not in response.content.lower()


def test_edit_duplicate_disable_enable_and_delete_workflows(client, rule_context):
    _user, _organization, _membership, item = rule_context
    rule = create_rule(client, item)

    edit = client.post(
        reverse("policies:edit", args=(rule.id,)),
        rule_payload(item, name="Updated payroll control"),
    )
    assert edit.status_code == 302
    rule.refresh_from_db()
    assert rule.name == "Updated payroll control"
    assert rule.version == 2

    duplicate = client.post(reverse("policies:duplicate", args=(rule.id,)))
    assert duplicate.status_code == 302
    copied = OrganizationRule.objects.exclude(pk=rule.id).get()
    assert copied.name == "Updated payroll control (copy)"
    assert copied.version == 1
    assert copied.definition == rule.definition

    disabled = client.post(reverse("policies:toggle", args=(rule.id,)))
    assert disabled.status_code == 302
    rule.refresh_from_db()
    assert rule.enabled is False
    assert rule.version == 3
    client.post(reverse("policies:toggle", args=(rule.id,)))
    rule.refresh_from_db()
    assert rule.enabled is True
    assert rule.version == 4

    deleted = client.post(reverse("policies:delete", args=(copied.id,)))
    assert deleted.status_code == 302
    assert not OrganizationRule.objects.filter(pk=copied.id).exists()

    events = list(AuditEvent.objects.order_by("occurred_at", "id"))
    assert [event.event_type for event in events] == [
        "rule.created",
        "rule.changed",
        "rule.created",
        "rule.changed",
        "rule.changed",
        "rule.changed",
    ]
    assert [event.data.get("change") for event in events[3:]] == [
        "disabled",
        "enabled",
        "deleted",
    ]
    assert all(event.entity_type == "organization_rule" for event in events)


def test_state_changes_are_post_only_and_csrf_protected(client, rule_context):
    user, organization, _membership, item = rule_context
    rule = create_rule(client, item)

    assert client.get(reverse("policies:duplicate", args=(rule.id,))).status_code == 405
    assert client.get(reverse("policies:toggle", args=(rule.id,))).status_code == 405
    assert client.get(reverse("policies:delete", args=(rule.id,))).status_code == 405

    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(user)
    session = csrf_client.session
    session["active_organization_id"] = str(organization.id)
    session.save()
    protected_requests = (
        (reverse("policies:create"), rule_payload(item)),
        (reverse("policies:edit", args=(rule.id,)), rule_payload(item)),
        (reverse("policies:duplicate", args=(rule.id,)), {}),
        (reverse("policies:toggle", args=(rule.id,)), {}),
        (reverse("policies:delete", args=(rule.id,)), {}),
    )
    assert all(
        csrf_client.post(url, data).status_code == 403
        for url, data in protected_requests
    )
    assert OrganizationRule.objects.filter(pk=rule.id).exists()


def test_viewer_can_read_but_cannot_change_rules(client, rule_context):
    _user, _organization, membership, item = rule_context
    rule = create_rule(client, item)
    membership.role = OrganizationMember.Role.VIEWER
    membership.save(update_fields=("role",))

    assert client.get(reverse("policies:list")).status_code == 200
    assert client.get(reverse("policies:detail", args=(rule.id,))).status_code == 200
    assert client.get(reverse("policies:create")).status_code == 403
    assert client.get(reverse("policies:edit", args=(rule.id,))).status_code == 403
    assert client.post(reverse("policies:toggle", args=(rule.id,))).status_code == 403


def test_rule_and_test_inventory_lookups_are_tenant_scoped(client, rule_context):
    _user, _organization, _membership, item = rule_context
    other_organization = Organization.objects.create(name="Other Rules Firm")
    other_user = get_user_model().objects.create_user("other-rules@example.com")
    other_item = InventoryItem.objects.create(
        organization=other_organization,
        display_name="Other Software",
        vendor_name="Other Vendor",
    )
    other_rule = OrganizationRule.objects.create(
        organization=other_organization,
        name="Other rule",
        definition={
            "all": [{"field": "status", "operator": "equals", "value": "active"}],
            "effects": [{"type": "severity_floor", "value": "HIGH"}],
        },
        result_on_match=OrganizationRule.Result.FAIL,
        severity=OrganizationRule.Severity.HIGH,
        explanation="Other tenant explanation.",
        remediation="Other tenant remediation.",
        created_by=other_user,
    )

    assert (
        client.get(reverse("policies:detail", args=(other_rule.id,))).status_code == 404
    )
    attempted_test = client.post(
        reverse("policies:create"),
        rule_payload(item, action="test", test_item=str(other_item.id)),
    )
    assert attempted_test.status_code == 200
    assert b"Select a valid choice" in attempted_test.content
    assert OrganizationRule.objects.count() == 1


@pytest.mark.parametrize(
    "definition",
    [
        {
            "all": [{"field": "status", "operator": "equals", "value": "active"}],
            "effects": [{"type": "block_software", "value": True}],
        },
        {
            "all": [{"field": "status", "operator": "execute_python", "value": "x"}],
            "effects": [{"type": "severity_floor", "value": "HIGH"}],
        },
        {
            "all": [],
            "effects": [],
            "python": "eval(customer_input)",
        },
    ],
)
def test_compiler_fails_closed_on_enforcement_or_executable_definitions(definition):
    record = OrganizationRule(
        name="Unsafe",
        definition=definition,
        result_on_match=OrganizationRule.Result.FAIL,
        severity=OrganizationRule.Severity.HIGH,
        explanation="Unsafe definition.",
        remediation="Reject it.",
    )

    with pytest.raises((PolicyDefinitionError, TypeError, ValueError)):
        compile_organization_rule(record)


def test_builder_output_is_json_data_without_executable_content(client, rule_context):
    _user, _organization, _membership, item = rule_context
    rule = create_rule(client, item)
    encoded = json.dumps(rule.definition, sort_keys=True)

    assert all(
        forbidden not in encoded.lower()
        for forbidden in ("eval(", "exec(", "python", "javascript", "sql")
    )


def test_organization_rule_cannot_subtract_risk(client, rule_context):
    _user, _organization, _membership, item = rule_context

    response = client.post(
        reverse("policies:create"),
        rule_payload(item, risk_points="-1"),
    )

    assert response.status_code == 200
    assert b"Ensure this value is greater than or equal to 0" in response.content
    assert OrganizationRule.objects.count() == 0
