"""Gated owner journey over admitted evidence; GET never admits new work."""

from functools import wraps
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.assessments.models import AssessmentSnapshot
from apps.assessments.snapshots import canonical_sha256, verify_snapshot
from apps.jobs.contracts import BranchProfile, Operation, WorkflowRequest
from apps.jobs.core_decisions import record_decision
from apps.jobs.core_models import ActionCardRevision, DecisionEvent
from apps.jobs.core_workflows import dispatch, require_owner
from apps.organizations.models import OrganizationMember, WorkflowProfile

from .comparison import compare_snapshots
from .exposure import review_record
from .forms import ComparisonForm, DecisionForm, FreezeForm, UnusedStopForm
from .models import ArtifactRequest, PackIdentity
from .services import freeze_cycle, open_cycle, request_pack_artifact


def _private(response):
    response["Cache-Control"] = "private, no-store"
    return response


def owner_workspace(view):
    @login_required
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not getattr(settings, "CORE_REVIEW_WORKSPACE_ENABLED", False):
            return _private(
                HttpResponse(
                    "Core evidence review workspace is unavailable "
                    "while qualification gates are closed.",
                    status=503,
                )
            )
        org = getattr(request, "organization_id", None)
        if org is None:
            raise Http404("Choose a workspace first")
        member = get_object_or_404(
            OrganizationMember, organization_id=org, user_id=request.user.id
        )
        if member.role != OrganizationMember.Role.OWNER:
            raise PermissionDenied("Evidence review requires workspace owner authority")
        return _private(view(request, *args, **kwargs))

    return guarded


def _snapshot(org, identity):
    snapshot = get_object_or_404(AssessmentSnapshot, id=identity, organization_id=org)
    if not verify_snapshot(snapshot):
        raise ValidationError("Captured evidence integrity failed")
    schema = snapshot.input_payload.get("snapshot_schema_version")
    if type(schema) is not int or schema not in {1, 2}:
        raise ValidationError("Unsupported captured evidence contract")
    if schema == 2:
        from apps.assessments.capture_contract import validate_capture_payloads
        from apps.assessments.models import SnapshotCaptureReceipt

        if not SnapshotCaptureReceipt.objects.filter(
            snapshot_id=snapshot.id,
            organization_id=org,
            created_by_id=snapshot.created_by_id,
        ).exists():
            raise ValidationError("Capture issuance receipt missing")
        validate_capture_payloads(
            {
                "input_payload": snapshot.input_payload,
                "result_payload": snapshot.result_payload,
                "input_sha256": snapshot.input_sha256,
                "result_sha256": snapshot.result_sha256,
            },
            organization_id=org,
            created_by_id=snapshot.created_by_id,
            workflow_profile_id=UUID(snapshot.input_payload["workflow_profile"]["id"]),
        )
    return snapshot


def _revision(org, identity):
    revision = get_object_or_404(
        ActionCardRevision.objects.select_related("snapshot"),
        id=identity,
        organization_id=org,
    )
    if (
        type(revision.cards) is not list
        or any(type(card) is not dict for card in revision.cards)
        or not verify_snapshot(revision.snapshot)
        or revision.input_sha256 != revision.snapshot.result_sha256
        or canonical_sha256(revision.cards) != revision.sha256
    ):
        raise ValidationError("Proposal evidence integrity failed")
    if revision.snapshot.input_payload.get("snapshot_schema_version") == 2:
        from .models import CaptureProposalAdmissionReceipt
        from .proposals_v1 import (
            APPLICABILITY_VERSION,
            VERSION,
            validate_review_proposals,
        )

        snapshot = _snapshot(org, revision.snapshot_id)
        receipt = CaptureProposalAdmissionReceipt.objects.filter(
            organization_id=org,
            revision_id=revision.id,
            snapshot_id=snapshot.id,
            created_by_id=revision.created_by_id,
            capture_receipt_id=snapshot.id,
            contract=VERSION,
            input_sha256=snapshot.input_sha256,
            result_sha256=snapshot.result_sha256,
            revision_sha256=revision.sha256,
            qualification_sha256=canonical_sha256(
                {
                    "schema": APPLICABILITY_VERSION,
                    "industry_applicability": snapshot.input_payload[
                        "industry_applicability"
                    ],
                    "ruleset": snapshot.input_payload["rulesets"]["industry"],
                    "engine_versions": snapshot.input_payload["engine_versions"],
                }
            ),
        ).first()
        if receipt is None:
            raise ValidationError("Proposal issuance receipt missing")
        validate_review_proposals(
            snapshot_id=snapshot.id,
            capture_envelope={
                "input_payload": snapshot.input_payload,
                "result_payload": snapshot.result_payload,
                "input_sha256": snapshot.input_sha256,
                "result_sha256": snapshot.result_sha256,
            },
            proposals=revision.cards,
        )
    return revision


def _integrity_unavailable():
    return HttpResponse(
        "Recorded evidence could not be verified. Content is withheld for review.",
        status=503,
    )


def _admission_unavailable():
    return HttpResponse(
        "This request could not be admitted under current deployment, owner, "
        "paid coverage, profile and health controls. No completion is claimed.",
        status=409,
    )


@owner_workspace
@require_GET
def history(request):
    org = request.organization_id
    snapshots = list(
        AssessmentSnapshot.objects.filter(organization_id=org).order_by(
            "-captured_at", "-id"
        )[:25]
    )
    page = Paginator(
        PackIdentity.objects.filter(organization_id=org)
        .select_related("cycle")
        .order_by("-created_at", "-id"),
        25,
    ).get_page(request.GET.get("page"))
    rows = []
    try:
        for pack in page.object_list:
            if canonical_sha256(pack.manifest) != pack.sha256 or pack.manifest.get(
                "organization_id"
            ) != str(org):
                raise ValidationError("Frozen identity invalid")
            rows.append({"pack": pack, "state": pack.cycle.state})
        if any(not verify_snapshot(snapshot) for snapshot in snapshots):
            raise ValidationError("Snapshot integrity invalid")
    except ValueError, ValidationError, KeyError, TypeError:
        return _integrity_unavailable()
    return render(
        request,
        "reviews/history.html",
        {
            "snapshots": snapshots,
            "rows": rows,
            "page": page,
            "deliberate_capture_enabled": getattr(
                settings, "DELIBERATE_CAPTURE_ENABLED", False
            ),
            "workflow_profile_recorded": WorkflowProfile.objects.filter(
                organization_id=org
            ).exists(),
        },
    )


@owner_workspace
@require_GET
def snapshot_review(request, snapshot_id):
    try:
        snapshot = _snapshot(request.organization_id, snapshot_id)
        exposures = [
            {"record": row, "review": review_record(row)}
            for row in snapshot.input_payload["inventory"]
        ]
        revision = ActionCardRevision.objects.filter(
            organization_id=request.organization_id, snapshot_id=snapshot.id
        ).first()
        if revision is not None:
            revision = _revision(request.organization_id, revision.id)
    except ValidationError, ValueError, KeyError, TypeError:
        return _integrity_unavailable()
    return render(
        request,
        "reviews/snapshot.html",
        {
            "snapshot": snapshot,
            "exposures": exposures,
            "revision": revision,
            "freeze_form": FreezeForm(initial={"cycle_id": uuid4()}),
            "proposals_enabled": (
                (
                    snapshot.input_payload.get("snapshot_schema_version") == 1
                    and getattr(settings, "CORE_WORKFLOWS_ENABLED", False)
                )
                or (
                    snapshot.input_payload.get("snapshot_schema_version") == 2
                    and getattr(settings, "CORE_PROPOSAL_ADMISSION_ENABLED", False)
                )
            ),
            "freeze_enabled": (
                snapshot.input_payload.get("snapshot_schema_version") == 1
                or getattr(settings, "REVIEW_PACK_LIFECYCLE_ENABLED", False)
            ),
        },
    )


@owner_workspace
@require_POST
def issue_proposals(request, snapshot_id):
    if not (
        getattr(settings, "CORE_WORKFLOWS_ENABLED", False)
        or getattr(settings, "CORE_PROPOSAL_ADMISSION_ENABLED", False)
    ):
        return HttpResponse(
            "Proposal admission is unavailable while its deployment gate is closed.",
            status=503,
        )
    try:
        snapshot = _snapshot(request.organization_id, snapshot_id)
    except ValidationError, ValueError, KeyError, TypeError:
        return _integrity_unavailable()
    if snapshot.input_payload.get("snapshot_schema_version") == 2:
        if not getattr(settings, "CORE_PROPOSAL_ADMISSION_ENABLED", False):
            return HttpResponse(
                "Capture proposal admission is unavailable.", status=503
            )
        from .proposal_admission import issue_capture_proposals

        try:
            issue_capture_proposals(
                organization_id=request.organization_id,
                actor_id=request.user.id,
                snapshot_id=snapshot.id,
            )
        except ValidationError, DatabaseError, ObjectDoesNotExist, ValueError:
            return _admission_unavailable()
        return redirect("reviews:snapshot", snapshot_id=snapshot.id)
    if not getattr(settings, "CORE_WORKFLOWS_ENABLED", False):
        return HttpResponse("Legacy proposal admission is unavailable.", status=503)
    try:
        with transaction.atomic():
            profile = require_owner(request.organization_id, request.user.id)
            dispatch(
                WorkflowRequest(
                    organization_id=request.organization_id,
                    operation=Operation.REASSESS,
                    receipt_ids=(snapshot.id,),
                    effective_at=timezone.now(),
                    branch_profile=BranchProfile(profile.profile),
                ),
                actor_id=request.user.id,
            )
    except ValidationError, DatabaseError, ObjectDoesNotExist, ValueError:
        return _admission_unavailable()
    return redirect("reviews:snapshot", snapshot_id=snapshot.id)


@owner_workspace
@require_http_methods(["GET", "POST"])
def decision(request, revision_id, card_index):
    try:
        revision = _revision(request.organization_id, revision_id)
    except ValidationError, ValueError, KeyError, TypeError:
        return _integrity_unavailable()
    if card_index >= len(revision.cards):
        raise Http404("Proposal not found")
    events = list(
        DecisionEvent.objects.filter(
            organization_id=request.organization_id,
            revision_id=revision.id,
            card_index=card_index,
        ).order_by("-sequence")[:25]
    )
    if any(
        canonical_sha256(event.payload) != event.sha256
        or event.card_sha256 != canonical_sha256(revision.cards[card_index])
        for event in events
    ):
        return _integrity_unavailable()
    capture = revision.snapshot.input_payload.get("snapshot_schema_version") == 2
    proposal = revision.cards[card_index]
    if capture and any(
        event.payload.get("schema") != "stewardence.core_decision_event.v2"
        or event.payload.get("proposal_id") != proposal["proposal_id"]
        or event.payload.get("proposal_sha256") != proposal["sha256"]
        or event.payload.get("source_class") != proposal["source"]["class"]
        or event.payload.get("source_identity") != proposal["source"]["identity"]
        or event.payload.get("source_digest") != proposal["source"]["digest"]
        or event.payload.get("original_outcome") != proposal["original_outcome"]
        or event.payload.get("resolution_effect") != "none"
        or event.payload.get("owner_statement_only") is not True
        or event.payload.get("resolution_verified") is not False
        for event in events
    ):
        return _integrity_unavailable()
    enabled = getattr(settings, "DECISION_DESK_ENABLED", False)
    if capture:
        enabled = enabled and getattr(
            settings, "CORE_PROPOSAL_ADMISSION_ENABLED", False
        )
    form = DecisionForm(
        request.POST if request.method == "POST" else None,
        initial={"expected_previous_event": events[0].id if events else None},
    )
    status = 200
    if request.method == "POST":
        if not enabled:
            return HttpResponse(
                "Owner statement admission is unavailable "
                "while its deployment gate is closed.",
                status=503,
            )
        if form.is_valid():
            try:
                with transaction.atomic():
                    issuer = record_decision
                    binding = {}
                    if capture:
                        from apps.jobs.core_decisions_v2 import record_capture_decision

                        issuer = record_capture_decision
                        binding = {
                            "proposal_id": UUID(proposal["proposal_id"]),
                            "proposal_sha256": proposal["sha256"],
                        }
                    issuer(
                        organization_id=request.organization_id,
                        actor_id=request.user.id,
                        revision_id=revision.id,
                        card_index=card_index,
                        **binding,
                        **form.cleaned_data,
                    )
            except ValidationError, DatabaseError, ObjectDoesNotExist, ValueError:
                form.add_error(
                    None,
                    "The exact proposal history changed or admission is unavailable. "
                    "Review current evidence before submitting again.",
                )
                status = 409
            else:
                return redirect(
                    "reviews:decision", revision_id=revision.id, card_index=card_index
                )
        else:
            status = 400
    return render(
        request,
        "reviews/capture_decision.html" if capture else "reviews/decision.html",
        {
            "revision": revision,
            "card": revision.cards[card_index],
            "card_index": card_index,
            "events": events,
            "form": form,
            "decisions_enabled": enabled,
        },
        status=status,
    )


@owner_workspace
@require_POST
def freeze(request, snapshot_id):
    try:
        snapshot = _snapshot(request.organization_id, snapshot_id)
    except ValidationError, ValueError, KeyError, TypeError:
        return _integrity_unavailable()
    form = FreezeForm(request.POST)
    if not form.is_valid():
        return HttpResponse(
            "A valid exact freeze request identity is required.", status=400
        )
    try:
        with transaction.atomic():
            cycle = open_cycle(
                organization_id=request.organization_id,
                actor_id=request.user.id,
                input_snapshot_id=snapshot.id,
                cycle_id=form.cleaned_data["cycle_id"],
            )
            pack = freeze_cycle(
                cycle_id=cycle.id,
                organization_id=request.organization_id,
                actor_id=request.user.id,
                expected_revision=1,
            )
    except ValidationError, DatabaseError, ObjectDoesNotExist, ValueError:
        return _admission_unavailable()
    return redirect("reviews:pack-detail", pack_id=pack.id)


def _frozen_entries(pack, snapshot):
    manifest = pack.manifest
    if manifest.get("schema") == "stewardence.review_pack.v4":
        from .capture_pack_reads import read_frozen_capture_entries

        return read_frozen_capture_entries(pack, snapshot)
    if (
        canonical_sha256(manifest) != pack.sha256
        or manifest.get("organization_id") != str(pack.organization_id)
        or manifest.get("cycle_id") != str(pack.cycle_id)
        or manifest["snapshot"]["snapshot_id"] != str(snapshot.id)
        or manifest["snapshot"]["input_sha256"] != snapshot.input_sha256
        or manifest["snapshot"]["result_sha256"] != snapshot.result_sha256
    ):
        raise ValidationError("Frozen pack pins invalid")
    entries = []
    for selected in manifest["selected_decisions"]:
        event = DecisionEvent.objects.select_related("revision").get(
            id=UUID(selected["event_id"]), organization_id=pack.organization_id
        )
        revision = event.revision
        if event.card_index >= len(revision.cards):
            raise ValidationError("Frozen card index invalid")
        proposal = revision.cards[event.card_index]
        if (
            canonical_sha256(event.payload) != event.sha256
            or event.sha256 != selected["event_sha256"]
            or canonical_sha256(revision.cards) != revision.sha256
            or revision.sha256 != selected["revision_sha256"]
            or canonical_sha256(proposal) != selected["card_sha256"]
            or revision.snapshot_id != snapshot.id
            or event.snapshot_id != snapshot.id
            or event.payload["id"] != selected["event_id"]
            or event.payload["owner_statement_only"] is not True
            or event.payload["resolution_verified"] is not False
            or any(
                event.payload[key] != selected[key]
                for key in (
                    "revision_id",
                    "revision_sha256",
                    "card_index",
                    "card_sha256",
                    "snapshot_id",
                    "snapshot_result_sha256",
                    "event_kind",
                    "state",
                )
            )
        ):
            raise ValidationError("Frozen owner statement invalid")
        entries.append({"selection": selected, "event": event, "proposal": proposal})
    return entries


@owner_workspace
@require_GET
def pack_detail(request, pack_id):
    pack = get_object_or_404(
        PackIdentity.objects.select_related("cycle"),
        id=pack_id,
        organization_id=request.organization_id,
    )
    try:
        snapshot = _snapshot(request.organization_id, pack.cycle.input_snapshot_id)
        entries = _frozen_entries(pack, snapshot)
        exposures = [
            {"record": row, "review": review_record(row)}
            for row in snapshot.input_payload["inventory"]
        ]
    except ValidationError, ValueError, KeyError, TypeError, ObjectDoesNotExist:
        return _integrity_unavailable()
    artifact_request = (
        ArtifactRequest.objects.filter(
            pack_id=pack.id, organization_id=request.organization_id
        )
        .select_related("job", "report")
        .first()
    )
    completed = artifact_request is not None and hasattr(artifact_request, "completion")
    return render(
        request,
        "reviews/pack.html",
        {
            "pack": pack,
            "snapshot": snapshot,
            "entries": entries,
            "frozen_proposals": pack.manifest.get("selected_proposals", []),
            "exposures": exposures,
            "artifact_request": artifact_request,
            "completed": completed,
            "state": pack.cycle.state,
            "artifact_enabled": getattr(
                settings, "REVIEW_PACK_LIFECYCLE_ENABLED", False
            )
            and pack.cycle.state == "FROZEN",
            "unused_stop_enabled": (
                getattr(settings, "REVIEW_UNUSED_STOP_ENABLED", False)
                and pack.manifest.get("schema") == "stewardence.review_pack.v4"
                and pack.cycle.state == "FROZEN"
                and artifact_request is None
            ),
            "unused_stop_form": UnusedStopForm(),
        },
    )


@owner_workspace
@require_POST
def stop_unused_pack_view(request, pack_id):
    pack = get_object_or_404(
        PackIdentity, id=pack_id, organization_id=request.organization_id
    )
    if not getattr(settings, "REVIEW_UNUSED_STOP_ENABLED", False):
        return HttpResponse("Unused report stopping is unavailable.", status=503)
    form = UnusedStopForm(request.POST)
    if not form.is_valid():
        return HttpResponse("Choose an exact unused-stop reason.", status=400)
    from .unused_stop import stop_unused_pack

    try:
        event = stop_unused_pack(
            pack_id=pack.id,
            organization_id=request.organization_id,
            actor_id=request.user.id,
            reason=form.cleaned_data["reason"],
        )
        if (
            type(event.payload) is not dict
            or set(event.payload)
            != {
                "schema",
                "cycle_id",
                "pack_id",
                "manifest_sha256",
                "reservation_id",
                "actor_id",
                "reason",
                "state",
                "reservation_state",
                "monthly_allowance_refunded",
                "proof_scope",
            }
            or event.payload.get("schema") != "stewardence.review_unused_stop.v1"
            or canonical_sha256(event.payload) != event.sha256
            or event.organization_id != request.organization_id
            or event.created_by_id != request.user.id
            or event.payload.get("pack_id") != str(pack.id)
            or event.payload.get("manifest_sha256") != pack.sha256
            or event.payload.get("cycle_id") != str(pack.cycle_id)
            or event.payload.get("actor_id") != str(request.user.id)
            or event.payload.get("reason") != form.cleaned_data["reason"]
            or event.payload.get("state") != "TERMINATED_UNUSED"
            or event.payload.get("reservation_state") != "proven_unused"
            or event.payload.get("monthly_allowance_refunded") is not False
            or event.payload.get("proof_scope") != "no_admitted_report_work"
            or event.cycle_id != pack.cycle_id
            or event.revision != 4
            or event.state != "TERMINATED_UNUSED"
        ):
            raise ValidationError("Unused-stop receipt binding failed")
    except ValidationError, DatabaseError, ObjectDoesNotExist, ValueError:
        return _admission_unavailable()
    return render(request, "reviews/unused_stop.html", {"pack": pack, "event": event})


@owner_workspace
@require_POST
def request_artifact(request, pack_id):
    get_object_or_404(PackIdentity, id=pack_id, organization_id=request.organization_id)
    if not getattr(settings, "REVIEW_PACK_LIFECYCLE_ENABLED", False):
        return HttpResponse(
            "Private PDF preparation is unavailable "
            "while its deployment gate is closed.",
            status=503,
        )
    try:
        with transaction.atomic():
            request_pack_artifact(
                pack_id=pack_id,
                organization_id=request.organization_id,
                actor_id=request.user.id,
                expected_revision=3,
                promote_baseline=False,
            )
    except ValidationError, DatabaseError, ObjectDoesNotExist, ValueError:
        return _admission_unavailable()
    return redirect("reviews:pack-detail", pack_id=pack_id)


@owner_workspace
@require_GET
def comparison(request):
    form = ComparisonForm(request.GET or None, organization_id=request.organization_id)
    result = None
    status = 200
    if request.GET:
        if form.is_valid():
            try:
                result = compare_snapshots(
                    baseline=_snapshot(
                        request.organization_id, form.cleaned_data["baseline"].id
                    ),
                    current=_snapshot(
                        request.organization_id, form.cleaned_data["current"].id
                    ),
                    organization_id=request.organization_id,
                )
            except ValidationError, ValueError, KeyError, TypeError:
                form.add_error(
                    None,
                    "Comparison requires intact same-workspace snapshots "
                    "in captured-time order.",
                )
                status = 400
        else:
            status = 400
    return render(
        request,
        "reviews/comparison.html",
        {"form": form, "comparison": result},
        status=status,
    )
