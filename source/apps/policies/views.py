from __future__ import annotations

import json
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods

from apps.audit.append import append_audit_event
from apps.audit.events import EVENT_RULE_CHANGED, EVENT_RULE_CREATED
from apps.organizations.models import OrganizationMember

from .context import inventory_policy_context
from .engine import evaluate_rule
from .forms import OrganizationRuleForm
from .models import OrganizationRule
from .organization_rules import compile_organization_rule

WRITE_ROLES = {
    OrganizationMember.Role.OWNER,
    OrganizationMember.Role.ADMIN,
    OrganizationMember.Role.ASSESSOR,
}


def _organization_id(request):
    organization_id = getattr(request, "organization_id", None)
    if organization_id is None:
        raise Http404("Choose a firm before opening its rules.")
    return organization_id


def _membership(request):
    return get_object_or_404(
        OrganizationMember,
        user_id=request.user.id,
        organization_id=_organization_id(request),
    )


def _require_writer(request):
    membership = _membership(request)
    if membership.role not in WRITE_ROLES:
        raise PermissionDenied("Your role has read-only access to these rules.")
    return membership


def _rule(request, rule_id):
    return get_object_or_404(
        OrganizationRule,
        id=rule_id,
        organization_id=_organization_id(request),
    )


def _candidate_from_form(form, *, organization_id, created_by_id, current=None):
    candidate = form.save(commit=False)
    candidate.id = current.id if current else uuid.uuid4()
    candidate.organization_id = organization_id
    candidate.created_by_id = created_by_id
    candidate.version = current.version if current else 1
    candidate.definition = form.structured_definition()
    return candidate


def _render_rule_form(request, form, *, mode, current=None):
    test_evaluation = None
    if request.method == "POST" and form.is_valid():
        candidate = _candidate_from_form(
            form,
            organization_id=_organization_id(request),
            created_by_id=request.user.id,
            current=current,
        )
        if request.POST.get("action") == "test":
            test_item = form.cleaned_data.get("test_item")
            if test_item is None:
                form.add_error(
                    "test_item", "Choose software to test this rule against."
                )
            else:
                test_evaluation = evaluate_rule(
                    compile_organization_rule(candidate),
                    inventory_policy_context(test_item),
                )
        elif request.POST.get("action") == "save":
            event_type = EVENT_RULE_CREATED
            if current:
                candidate.version = current.version + 1
                event_type = EVENT_RULE_CHANGED
            candidate.save()
            append_audit_event(
                organization_id=candidate.organization_id,
                actor_user_id=request.user.id,
                event_type=event_type,
                entity_type="organization_rule",
                entity_id=candidate.id,
                data={
                    "enabled": candidate.enabled,
                    "version": str(candidate.version),
                },
            )
            messages.success(request, f"{candidate.name} was saved.")
            return redirect("policies:detail", rule_id=candidate.id)
    return render(
        request,
        "policies/form.html",
        {
            "form": form,
            "mode": mode,
            "rule": current,
            "test_evaluation": test_evaluation,
        },
    )


@login_required
def list_rules_view(request):
    membership = _membership(request)
    rules = OrganizationRule.objects.filter(organization_id=_organization_id(request))
    return render(
        request,
        "policies/list.html",
        {"rules": rules, "can_write": membership.role in WRITE_ROLES},
    )


@login_required
def detail_rule_view(request, rule_id):
    rule = _rule(request, rule_id)
    membership = _membership(request)
    compile_organization_rule(rule)
    can_write = membership.role in WRITE_ROLES
    return render(
        request,
        "policies/detail.html",
        {
            "rule": rule,
            "can_write": can_write,
            "can_edit": can_write
            and rule.source_type == OrganizationRule.SourceType.MANUAL,
            "definition_json": json.dumps(rule.definition, indent=2, sort_keys=True),
        },
    )


@login_required
@transaction.atomic
@require_http_methods(["GET", "POST"])
def create_rule_view(request):
    _require_writer(request)
    form = OrganizationRuleForm(
        request.POST or None,
        organization_id=_organization_id(request),
    )
    return _render_rule_form(request, form, mode="Create")


@login_required
@transaction.atomic
@require_http_methods(["GET", "POST"])
def edit_rule_view(request, rule_id):
    _require_writer(request)
    rule = _rule(request, rule_id)
    if rule.source_type == OrganizationRule.SourceType.DETECTOR:
        raise PermissionDenied(
            "Collector-created rules retain their provenance and cannot be edited."
        )
    form = OrganizationRuleForm(
        request.POST or None,
        instance=rule,
        organization_id=_organization_id(request),
    )
    return _render_rule_form(request, form, mode="Edit", current=rule)


@login_required
@require_POST
@transaction.atomic
def duplicate_rule_action(request, rule_id):
    _require_writer(request)
    source = _rule(request, rule_id)
    if source.source_type == OrganizationRule.SourceType.DETECTOR:
        raise PermissionDenied(
            "Collector-created rules retain their provenance and cannot be duplicated."
        )
    compile_organization_rule(source)
    base_name = f"{source.name} (copy)"
    name = base_name
    suffix = 2
    while OrganizationRule.objects.filter(
        organization_id=_organization_id(request), name=name
    ).exists():
        name = f"{base_name} {suffix}"
        suffix += 1
    duplicate = OrganizationRule.objects.create(
        organization_id=_organization_id(request),
        name=name,
        definition=source.definition,
        result_on_match=source.result_on_match,
        severity=source.severity,
        explanation=source.explanation,
        remediation=source.remediation,
        enabled=source.enabled,
        created_by_id=request.user.id,
    )
    append_audit_event(
        organization_id=duplicate.organization_id,
        actor_user_id=request.user.id,
        event_type=EVENT_RULE_CREATED,
        entity_type="organization_rule",
        entity_id=duplicate.id,
        data={
            "source_rule_id": str(source.id),
            "version": str(duplicate.version),
        },
    )
    messages.success(request, f"{source.name} was duplicated.")
    return redirect("policies:detail", rule_id=duplicate.id)


@login_required
@require_POST
@transaction.atomic
def toggle_rule_action(request, rule_id):
    _require_writer(request)
    rule = _rule(request, rule_id)
    rule.enabled = not rule.enabled
    rule.version += 1
    rule.save(update_fields=("enabled", "version", "updated_at"))
    append_audit_event(
        organization_id=rule.organization_id,
        actor_user_id=request.user.id,
        event_type=EVENT_RULE_CHANGED,
        entity_type="organization_rule",
        entity_id=rule.id,
        data={
            "change": "enabled" if rule.enabled else "disabled",
            "version": str(rule.version),
        },
    )
    messages.success(
        request, f"{rule.name} is now {'enabled' if rule.enabled else 'disabled'}."
    )
    return redirect("policies:detail", rule_id=rule.id)


@login_required
@require_POST
@transaction.atomic
def delete_rule_action(request, rule_id):
    _require_writer(request)
    rule = _rule(request, rule_id)
    if rule.source_type == OrganizationRule.SourceType.DETECTOR:
        raise PermissionDenied(
            "Collector-created rules retain their provenance and cannot be deleted."
        )
    name = rule.name
    append_audit_event(
        organization_id=rule.organization_id,
        actor_user_id=request.user.id,
        event_type=EVENT_RULE_CHANGED,
        entity_type="organization_rule",
        entity_id=rule.id,
        data={
            "change": "deleted",
            "version": str(rule.version),
        },
    )
    rule.delete()
    messages.success(request, f"{name} was deleted.")
    return redirect("policies:list")
