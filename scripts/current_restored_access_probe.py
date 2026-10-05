"""Run only in disposable actual app image, over restored RAM objects.

No entitlement fabrication, provider request or listening HTTP server. Clone
bootstrap credentials are isolated test authority and are never printed.
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import django

django.setup()

from agentledger.settings.base import database_from_url
from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.billing.entitlements import paid_subscription_access
from apps.billing.models import Subscription
from apps.organizations.models import Organization, OrganizationMember
from apps.reports.models import ReportArtifact
from apps.reviews.capture_pack_reads import read_frozen_capture_entries
from apps.reviews.models import PackCompletion
from django.contrib.auth import get_user_model
from django.db import connections
from django.test import Client, override_settings
from django.urls import reverse


def logged(user, org):
    client = Client()
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(org)
    session.save()
    return client


def denial(response, statuses):
    assert response.status_code in statuses
    assert response.get("Content-Type", "").split(";")[0] != "application/pdf"
    assert response.get("Content-Disposition") is None


def main():
    for name in ("django.request", "agentledger.tenancy.middleware"):
        logging.getLogger(name).disabled = True
    if os.environ.get("CURRENT_RESTORE_ISOLATED") != "1":
        raise RuntimeError("Explicit isolated restore probe required")
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT current_user,current_setting('transaction_isolation')")
        assert cursor.fetchone() == ("agentledger_app", "read committed")
    from django.conf import settings

    settings.DATABASES["bootstrap"] = database_from_url(
        os.environ["CURRENT_RESTORE_BOOTSTRAP_DATABASE_URL"]
    )
    connections.configure_settings(settings.DATABASES)
    with connections["bootstrap"].cursor() as cursor:
        cursor.execute("SELECT current_database(),current_user")
        assert cursor.fetchone() == ("restored", "postgres")
    manifest = json.loads(Path("/restore/manifest.json").read_text(encoding="utf-8"))
    objects = manifest["objects"]
    assert len(objects) == 2
    user_model = get_user_model()
    # Explicit negative tenant fixtures only. No coverage, subscription,
    # immutable report, snapshot, original membership or receipt is changed.
    foreign_user = user_model.objects.db_manager("bootstrap").create_user(
        str(uuid4()) + "@restore.example.invalid"
    )
    foreign_org = Organization.objects.using("bootstrap").create(
        name="Synthetic isolated restore negative tenant"
    )
    OrganizationMember.objects.using("bootstrap").create(
        organization=foreign_org, user=foreign_user, role="owner"
    )
    counts = {
        key: 0
        for key in (
            "owner_pack_reads",
            "owner_downloads",
            "anonymous_denials",
            "same_tenant_viewer_denials",
            "cross_tenant_denials",
            "missing_object_denials",
            "changed_length_denials",
            "same_length_denials",
            "recovered_downloads",
            "immutable_metadata_matches",
        )
    }
    root = Path("/restore/private")
    with override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["testserver"],
        SECURE_SSL_REDIRECT=False,
        CORE_REVIEW_WORKSPACE_ENABLED=True,
        REPORTS_STORAGE_BACKEND="local",
        REPORTS_LOCAL_STORAGE_ROOT=root,
        PUBLIC_MAINTENANCE_MODE=False,
        AUTOMATION_ENABLED=False,
        CORE_WORKFLOWS_ENABLED=False,
        QUICKBOOKS_PREVIEW_ENABLED=False,
        MICROSOFT_PREVIEW_ENABLED=False,
        XERO_PREVIEW_ENABLED=False,
    ):
        for item in objects:
            artifact = ReportArtifact.objects.using("bootstrap").get(
                pk=item["artifact_id"]
            )
            assert (
                str(artifact.report_id) == item["report_id"]
                and str(artifact.organization_id) == item["organization_id"]
                and str(artifact.assessment_snapshot_id) == item["snapshot_id"]
            )
            assert (
                artifact.object_key == item["object_key"]
                and artifact.sha256 == item["sha256"]
                and artifact.size_bytes == item["size_bytes"]
            )
            completion = (
                PackCompletion.objects.using("bootstrap")
                .select_related("request__pack")
                .get(pk=item["completion_id"])
            )
            pack = completion.request.pack
            owner_id = artifact.report.created_by_id
            owner = user_model.objects.using("bootstrap").get(pk=owner_id)
            viewer_id = (
                OrganizationMember.objects.using("bootstrap")
                .filter(organization_id=artifact.organization_id, role="viewer")
                .values_list("user_id", flat=True)
                .first()
            )
            assert viewer_id is not None
            same_viewer = user_model.objects.using("bootstrap").get(pk=viewer_id)
            with (
                identity_transaction(owner_id),
                tenant_transaction(artifact.organization_id),
            ):
                subscription = Subscription.objects.get(
                    organization_id=artifact.organization_id,
                    billing_customer__user_id=owner_id,
                )
                assert paid_subscription_access(subscription.id)
                assert (
                    len(read_frozen_capture_entries(pack, artifact.assessment_snapshot))
                    == len(pack.manifest["selected_decisions"])
                    > 0
                )
            owner_client = logged(owner, artifact.organization_id)
            path = reverse("reports:download", args=[artifact.report_id])
            pack_path = reverse("reviews:pack-detail", args=[pack.id])
            response = owner_client.get(pack_path)
            assert (
                response.status_code == 200
                and "Original captured outcome: UNKNOWN" in response.content.decode()
            )
            counts["owner_pack_reads"] += 1
            response = owner_client.get(path)
            assert (
                response.status_code == 200
                and hashlib.sha256(response.content).hexdigest() == item["sha256"]
                and len(response.content) == item["size_bytes"]
            )
            assert response.get("Cache-Control") == "private, no-store"
            counts["owner_downloads"] += 1
            original = (root / item["object_key"]).read_bytes()
            artifact_before = {
                field: str(getattr(artifact, field))
                for field in (
                    "id",
                    "organization_id",
                    "report_id",
                    "assessment_snapshot_id",
                    "object_key",
                    "sha256",
                    "size_bytes",
                )
            }

            def forbidden_storage():
                raise AssertionError(
                    "Unauthorized restored request reached private storage"
                )

            with patch("apps.reports.views._report_storage", forbidden_storage):
                denial(Client().get(path), {302})
                counts["anonymous_denials"] += 1
                # Isolate report/tenant privacy from the owner's personal paid
                # subscription. Keep auth, tenant and owner guards installed.
                middleware = [
                    entry
                    for entry in settings.MIDDLEWARE
                    if not entry.endswith("BillingEntitlementMiddleware")
                ]
                with override_settings(MIDDLEWARE=middleware):
                    denial(
                        logged(same_viewer, artifact.organization_id).get(path),
                        {403, 404},
                    )
                    counts["same_tenant_viewer_denials"] += 1
                    denial(logged(foreign_user, foreign_org.id).get(path), {403, 404})
                    counts["cross_tenant_denials"] += 1
            file = root / item["object_key"]
            for corrupt, key in (
                (b"%PDF-isolated-corruption", "changed_length_denials"),
                (original[:-1] + bytes([original[-1] ^ 1]), "same_length_denials"),
            ):
                file.write_bytes(corrupt)
                response = owner_client.get(path)
                denial(response, {503})
                assert response.get("Cache-Control") == "private, no-store"
                counts[key] += 1
            # Hide the owned disposable RAM copy; no object deletion occurs.
            hidden = file.with_suffix(".restore-missing-fixture")
            file.rename(hidden)
            denial(owner_client.get(path), {503})
            counts["missing_object_denials"] += 1
            hidden.rename(file)
            file.write_bytes(original)
            response = owner_client.get(path)
            assert (
                response.status_code == 200
                and hashlib.sha256(response.content).hexdigest() == item["sha256"]
            )
            counts["recovered_downloads"] += 1
            after = ReportArtifact.objects.using("bootstrap").get(pk=artifact.id)
            assert artifact_before == {
                field: str(getattr(after, field)) for field in artifact_before
            }
            counts["immutable_metadata_matches"] += 1
    assert all(value == 2 for value in counts.values())
    print(
        json.dumps(
            {
                "passed": True,
                "counts": counts,
                "application_role": "agentledger_app",
                "isolation": "read committed",
                "entitlement_fabricated": False,
                "original_paid_receipts_preserved": True,
                "negative_tenant": "Explicit new disposable clone fixture only",
                "live_providers_tested": False,
                "production_touched": False,
                "listening_http_server": False,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 -- suppress private restored identity diagnostics
        print(
            json.dumps(
                {
                    "passed": False,
                    "error_type": type(error).__name__,
                    "underlying_diagnostics": "suppressed",
                }
            )
        )
        raise SystemExit(1) from None
