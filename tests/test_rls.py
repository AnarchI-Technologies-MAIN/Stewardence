from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import psycopg
import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connections, transaction

from agentledger.tenancy.context import (
    activate_tenant,
    identity_transaction,
    tenant_transaction,
)
from apps.assessments.models import AssessmentSnapshot
from apps.assessments.snapshots import create_assessment_snapshot
from apps.catalog.models import Product, Vendor
from apps.imports.models import ImportBatch, ImportRow
from apps.inventory.models import InventoryItem
from apps.jobs.models import BackgroundJob
from apps.organizations.models import Organization, OrganizationMember
from apps.organizations.services import create_owned_workspace
from apps.policies.models import OrganizationRule
from apps.reports.models import Report, ReportArtifact
from apps.reports.services import create_report
from apps.reports.storage import build_pdf_object_key

pytestmark = [
    pytest.mark.rls,
    pytest.mark.skipif(
        os.getenv("AGENTLEDGER_RLS_TESTS") != "1",
        reason="run through scripts/verify_rls.py",
    ),
    pytest.mark.django_db(
        transaction=True,
        databases={"default", "owner_runtime", "app_runtime", "worker_runtime"},
    ),
]


@dataclass(frozen=True)
class IsolationFixture:
    user_a_id: UUID
    user_b_id: UUID
    organization_a_id: UUID
    organization_b_id: UUID
    item_a_id: UUID
    item_b_id: UUID


@pytest.fixture
def isolation_fixture():
    user_model = get_user_model()
    user_a = user_model.objects.create_user("rls-a@example.com")
    user_b = user_model.objects.create_user("rls-b@example.com")
    organization_a = Organization.objects.create(name="RLS Firm A")
    organization_b = Organization.objects.create(name="RLS Firm B")
    OrganizationMember.objects.create(
        user=user_a,
        organization=organization_a,
        role=OrganizationMember.Role.OWNER,
    )
    OrganizationMember.objects.create(
        user=user_b,
        organization=organization_b,
        role=OrganizationMember.Role.OWNER,
    )
    item_a = InventoryItem.objects.create(
        organization=organization_a,
        display_name="Inventory A",
        vendor_name="Vendor A",
    )
    item_b = InventoryItem.objects.create(
        organization=organization_b,
        display_name="Inventory B",
        vendor_name="Vendor B",
    )
    fixture = IsolationFixture(
        user_a.id,
        user_b.id,
        organization_a.id,
        organization_b.id,
        item_a.id,
        item_b.id,
    )
    yield fixture
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "TRUNCATE TABLE reports, audit_events, "
            "audit_merkle_blocks, audit_chain_heads, "
            "assessment_snapshots, billing_admission_receipt, "
            "billing_paid_coverage CASCADE"
        )
    BackgroundJob.objects.all().delete()
    from apps.billing.models import Subscription

    Subscription.objects.filter(
        organization_id__in=[fixture.organization_a_id, fixture.organization_b_id]
    ).delete()
    OrganizationRule.objects.all().delete()
    InventoryItem.objects.all().delete()
    OrganizationMember.objects.all().delete()
    Organization.objects.all().delete()
    user_model.objects.all().delete()


@pytest.fixture
def legacy_snapshot_factory(isolation_fixture, shared_roi_inputs):
    """Real schema-1 engine snapshots; fixture ROI assumptions are test inputs."""

    def create(organization_id, user_id, label):
        item = InventoryItem.objects.get(organization_id=organization_id)
        return create_assessment_snapshot(
            organization_id=organization_id,
            created_by_id=user_id,
            assessed_item_id=item.id,
            roi_inputs=shared_roi_inputs(),
            captured_at=datetime(2026, 9, 4, tzinfo=UTC),
            evidence_references=({"reference": label, "type": "customer_statement"},),
        )

    return create


def assert_insufficient_privilege(captured) -> None:
    assert isinstance(captured.value, DatabaseError)
    assert isinstance(captured.value.__cause__, psycopg.errors.InsufficientPrivilege)


def current_user(using: str) -> str:
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT current_user")
        return cursor.fetchone()[0]


def raw_inventory_ids(using: str) -> set[UUID]:
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT id FROM inventory_items")
        return {row[0] for row in cursor.fetchall()}


@pytest.mark.parametrize(
    ("using", "expected"),
    [
        ("owner_runtime", "agentledger_owner"),
        ("app_runtime", "agentledger_app"),
        ("worker_runtime", "agentledger_worker"),
    ],
)
def test_restricted_alias_uses_the_expected_database_identity(using, expected):
    assert current_user(using) == expected


def test_app_runtime_can_read_global_catalog_without_write_authority():
    vendor = Vendor.objects.create(name="RLS Catalog Vendor")
    Product.objects.create(vendor=vendor, name="RLS Catalog Product", category="Test")

    assert Product.objects.using("app_runtime").count() == 1
    with pytest.raises(DatabaseError) as captured:
        with transaction.atomic(using="app_runtime"):
            Vendor.objects.using("app_runtime").create(name="Forbidden Catalog Write")

    assert_insufficient_privilege(captured)


def test_database_roles_have_the_required_privilege_boundary():
    with connections["app_runtime"].cursor() as cursor:
        cursor.execute(
            """
            SELECT rolname, rolsuper, rolbypassrls, rolinherit, rolcanlogin
            FROM pg_roles
            WHERE rolname IN (
                'agentledger_owner', 'agentledger_app', 'agentledger_worker',
                'agentledger_billing_admission'
            )
            ORDER BY rolname
            """
        )
        assert cursor.fetchall() == [
            ("agentledger_app", False, False, False, True),
            ("agentledger_billing_admission", False, False, False, True),
            ("agentledger_owner", False, False, False, True),
            ("agentledger_worker", False, False, False, True),
        ]
        cursor.execute(
            """
            SELECT pg_get_userbyid(relowner)
            FROM pg_class
            WHERE oid = 'inventory_items'::regclass
            """
        )
        assert cursor.fetchone()[0] == "agentledger_owner"


def test_organization_scoped_tables_have_required_column_and_forced_rls():
    with connections["app_runtime"].cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, a.attnotnull
            FROM pg_class AS c
            JOIN pg_attribute AS a ON a.attrelid = c.oid
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND a.attname = 'organization_id'
              AND a.attnotnull
            ORDER BY c.relname
            """
        )
        scoped_tables = cursor.fetchall()
        assert all(row[1:] == (True, True, True) for row in scoped_tables)
        assert set(
            [
                ("assessment_snapshots", True, True, True),
                ("audit_chain_heads", True, True, True),
                ("audit_events", True, True, True),
                ("audit_merkle_blocks", True, True, True),
                ("background_jobs", True, True, True),
                ("core_action_card_revisions", True, True, True),
                ("core_health_controls", True, True, True),
                ("core_known_entities", True, True, True),
                ("core_workflow_runs", True, True, True),
                ("core_workflow_schedules", True, True, True),
                ("detection_evidence", True, True, True),
                ("discovery_scans", True, True, True),
                ("integrations_providerconnection", True, True, True),
                ("integrations_quickbooksconnection", True, True, True),
                ("inventory_import_batches", True, True, True),
                ("inventory_import_rows", True, True, True),
                ("inventory_items", True, True, True),
                ("job_recovery_receipts", True, True, True),
                ("organization_rules", True, True, True),
                ("organization_workflow_profiles", True, True, True),
                ("organizations_organizationmember", True, True, True),
                ("report_artifacts", True, True, True),
                ("reports", True, True, True),
                ("review_capacity_reservations", True, True, True),
                ("review_cycle_events", True, True, True),
                ("review_cycles", True, True, True),
                ("review_pack_identities", True, True, True),
                ("review_reservation_events", True, True, True),
            ]
        ) <= set(scoped_tables)

        cursor.execute(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, a.attnotnull
            FROM pg_class AS c
            JOIN pg_attribute AS a ON a.attrelid = c.oid
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND a.attname = 'organization_id'
              AND NOT a.attnotnull
            ORDER BY c.relname
            """
        )
        assert cursor.fetchall() == [
            ("billing_subscription", True, True, False),
        ]
        cursor.execute(
            """
            SELECT cmd, roles, qual IS NOT NULL, with_check IS NOT NULL
            FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = 'inventory_items'
              AND policyname = 'inventory_items_tenant_policy'
            """
        )
        assert cursor.fetchone() == (
            "ALL",
            ["agentledger_app", "agentledger_worker"],
            True,
            True,
        )


def test_assessment_snapshots_are_tenant_isolated_and_append_only(
    isolation_fixture, legacy_snapshot_factory
):
    fixture = isolation_fixture
    snapshot_a = legacy_snapshot_factory(
        fixture.organization_a_id, fixture.user_a_id, "RLS tenant A"
    )
    snapshot_b = legacy_snapshot_factory(
        fixture.organization_b_id, fixture.user_b_id, "RLS tenant B"
    )

    with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
        visible_ids = set(
            AssessmentSnapshot.objects.using("app_runtime").values_list("id", flat=True)
        )
    assert visible_ids == {snapshot_a.id}

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
            AssessmentSnapshot.objects.using("app_runtime").filter(
                pk=snapshot_a.id
            ).update(version=2)
    assert_insufficient_privilege(captured)

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
            AssessmentSnapshot.objects.using("app_runtime").filter(
                pk=snapshot_a.id
            ).delete()
    assert_insufficient_privilege(captured)

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
            AssessmentSnapshot.objects.using("app_runtime").create(
                organization_id=fixture.organization_b_id,
                created_by_id=fixture.user_b_id,
                captured_at=datetime(2026, 9, 4, tzinfo=UTC),
                input_payload=snapshot_b.input_payload,
                result_payload=snapshot_b.result_payload,
                input_sha256=snapshot_b.input_sha256,
                result_sha256=snapshot_b.result_sha256,
            )
    assert_insufficient_privilege(captured)


def test_reports_are_tenant_isolated_and_runtime_immutable(
    isolation_fixture,
    legacy_snapshot_factory,
):
    fixture = isolation_fixture
    snapshot_a = legacy_snapshot_factory(
        fixture.organization_a_id, fixture.user_a_id, "RLS tenant A"
    )
    snapshot_b = legacy_snapshot_factory(
        fixture.organization_b_id, fixture.user_b_id, "RLS tenant B"
    )
    report_a = Report.objects.create(
        organization_id=fixture.organization_a_id,
        assessment_snapshot=snapshot_a,
        sequence=900001,
        identifier_year=2026,
        report_identifier="AL-2026-900001",
        organization_display_name="RLS Firm A",
        created_by_id=fixture.user_a_id,
    )
    Report.objects.create(
        organization_id=fixture.organization_b_id,
        assessment_snapshot=snapshot_b,
        sequence=900002,
        identifier_year=2026,
        report_identifier="AL-2026-900002",
        organization_display_name="RLS Firm B",
        created_by_id=fixture.user_b_id,
    )

    # App report reads now require authenticated identity as well as tenant.
    # Reproduce the old fixture's missing context as an explicit denial probe.
    with pytest.raises(
        DatabaseError, match="Authenticated user context is not set"
    ) as missing_identity:
        with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
            list(Report.objects.using("app_runtime").values_list("id", flat=True))
    assert_insufficient_privilege(missing_identity)

    with (
        identity_transaction(fixture.user_a_id, using="app_runtime"),
        tenant_transaction(fixture.organization_a_id, using="app_runtime"),
    ):
        assert set(
            Report.objects.using("app_runtime").values_list(
                "id",
                flat=True,
            )
        ) == {report_a.id}

        with pytest.raises(DatabaseError) as captured:
            with transaction.atomic(using="app_runtime"):
                Report.objects.using("app_runtime").filter(id=report_a.id).update(
                    organization_display_name="Changed"
                )

    assert_insufficient_privilege(captured)

    with tenant_transaction(
        fixture.organization_a_id,
        using="worker_runtime",
    ):
        assert set(
            Report.objects.using("worker_runtime").values_list(
                "id",
                flat=True,
            )
        ) == {report_a.id}

        with pytest.raises(DatabaseError) as captured:
            with transaction.atomic(using="worker_runtime"):
                Report.objects.using("worker_runtime").filter(id=report_a.id).update(
                    organization_display_name="Changed"
                )

    assert_insufficient_privilege(captured)


def test_report_service_uses_restricted_app_role(
    isolation_fixture,
    legacy_snapshot_factory,
):
    fixture = isolation_fixture
    snapshot = legacy_snapshot_factory(
        fixture.organization_a_id, fixture.user_a_id, "RLS tenant A"
    )

    with identity_transaction(
        fixture.user_a_id,
        using="app_runtime",
    ):
        activate_tenant(
            fixture.organization_a_id,
            using="app_runtime",
        )
        report = create_report(
            organization_id=fixture.organization_a_id,
            assessment_snapshot_id=snapshot.id,
            created_by_id=fixture.user_a_id,
            using="app_runtime",
        )

    assert report.organization_id == fixture.organization_a_id
    assert report.report_identifier.startswith("AL-")


def test_app_role_cannot_link_report_to_another_tenants_snapshot(
    isolation_fixture,
    legacy_snapshot_factory,
):
    fixture = isolation_fixture
    snapshot_b = legacy_snapshot_factory(
        fixture.organization_b_id, fixture.user_b_id, "RLS tenant B"
    )

    with pytest.raises(DatabaseError):
        with identity_transaction(
            fixture.user_a_id,
            using="app_runtime",
        ):
            activate_tenant(
                fixture.organization_a_id,
                using="app_runtime",
            )
            Report.objects.using("app_runtime").create(
                organization_id=fixture.organization_a_id,
                assessment_snapshot_id=snapshot_b.id,
                sequence=910001,
                identifier_year=2026,
                report_identifier="AL-2026-910001",
                organization_display_name="RLS Firm A",
                created_by_id=fixture.user_a_id,
            )


def test_organization_rules_are_tenant_isolated_for_app_and_worker(
    isolation_fixture,
):
    fixture = isolation_fixture
    definition = {
        "all": [
            {"field": "data_categories", "operator": "contains", "value": "payroll"}
        ],
        "effects": [{"type": "severity_floor", "value": "HIGH"}],
    }
    rule_a = OrganizationRule.objects.create(
        organization_id=fixture.organization_a_id,
        name="Rule A",
        definition=definition,
        result_on_match=OrganizationRule.Result.FAIL,
        severity=OrganizationRule.Severity.HIGH,
        explanation="Firm A explanation.",
        remediation="Firm A next step.",
        created_by_id=fixture.user_a_id,
    )
    OrganizationRule.objects.create(
        organization_id=fixture.organization_b_id,
        name="Rule B",
        definition=definition,
        result_on_match=OrganizationRule.Result.FAIL,
        severity=OrganizationRule.Severity.HIGH,
        explanation="Firm B explanation.",
        remediation="Firm B next step.",
        created_by_id=fixture.user_b_id,
    )

    for using in ("app_runtime", "worker_runtime"):
        with tenant_transaction(fixture.organization_a_id, using=using):
            visible_ids = set(
                OrganizationRule.objects.using(using).values_list("id", flat=True)
            )
        assert visible_ids == {rule_a.id}

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
            OrganizationRule.objects.using("app_runtime").create(
                organization_id=fixture.organization_b_id,
                name="Forbidden Rule",
                definition=definition,
                result_on_match=OrganizationRule.Result.FAIL,
                severity=OrganizationRule.Severity.HIGH,
                explanation="Forbidden.",
                remediation="Forbidden.",
                created_by_id=fixture.user_b_id,
            )
    assert_insufficient_privilege(captured)

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(fixture.organization_a_id, using="worker_runtime"):
            OrganizationRule.objects.using("worker_runtime").filter(
                pk=rule_a.id
            ).update(enabled=False)
    assert_insufficient_privilege(captured)


def test_identity_bootstrap_exposes_only_the_users_own_membership(
    isolation_fixture,
):
    fixture = isolation_fixture
    with identity_transaction(fixture.user_a_id, using="app_runtime"):
        membership_organizations = set(
            OrganizationMember.objects.using("app_runtime").values_list(
                "organization_id", flat=True
            )
        )
        organization_ids = set(
            Organization.objects.using("app_runtime").values_list("id", flat=True)
        )

    assert membership_organizations == {fixture.organization_a_id}
    assert organization_ids == {fixture.organization_a_id}


def test_public_onboarding_works_under_restricted_app_role(isolation_fixture):
    user = (
        get_user_model()
        .objects.db_manager("app_runtime")
        .create_user("selfservice@example.com", "New-Strong!Password97")
    )
    assert user.check_password("New-Strong!Password97")
    assert not user.is_staff and not user.is_superuser
    new_id = create_owned_workspace(
        user_id=user.id, name="New firm", industry="other", using="app_runtime"
    )
    with identity_transaction(user.id, using="app_runtime"):
        membership = OrganizationMember.objects.using("app_runtime").get()
        assert membership.organization_id == new_id
        assert membership.role == "owner"
    with identity_transaction(isolation_fixture.user_a_id, using="app_runtime"):
        assert not Organization.objects.using("app_runtime").filter(id=new_id).exists()


def test_public_registration_cannot_create_privileged_account(isolation_fixture):
    with pytest.raises(DatabaseError) as captured:
        with transaction.atomic(using="app_runtime"):
            get_user_model().objects.db_manager("app_runtime").create_superuser(
                "escalation@example.com", "New-Strong!Password97"
            )
    assert_insufficient_privilege(captured)


def test_onboarding_does_not_grant_direct_membership_insert(isolation_fixture):
    with pytest.raises(DatabaseError) as captured:
        with identity_transaction(isolation_fixture.user_a_id, using="app_runtime"):
            OrganizationMember.objects.using("app_runtime").create(
                user_id=isolation_fixture.user_a_id,
                organization_id=isolation_fixture.organization_b_id,
                role="owner",
            )
    assert_insufficient_privilege(captured)


def test_worker_cannot_provision_workspace(isolation_fixture):
    with pytest.raises(DatabaseError) as captured:
        create_owned_workspace(
            user_id=isolation_fixture.user_a_id,
            name="Forbidden",
            industry="other",
            using="worker_runtime",
        )
    assert_insufficient_privilege(captured)


def test_app_role_unfiltered_orm_and_raw_sql_are_tenant_isolated(
    isolation_fixture,
):
    fixture = isolation_fixture
    with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
        orm_ids = set(
            InventoryItem.objects.using("app_runtime").values_list("id", flat=True)
        )
        sql_ids = raw_inventory_ids("app_runtime")

    assert orm_ids == {fixture.item_a_id}
    assert sql_ids == {fixture.item_a_id}


def test_direct_cross_tenant_primary_key_lookup_is_inaccessible(isolation_fixture):
    fixture = isolation_fixture
    with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
        exists = (
            InventoryItem.objects.using("app_runtime")
            .filter(pk=fixture.item_b_id)
            .exists()
        )

    assert exists is False


def test_cross_tenant_insert_is_rejected(isolation_fixture):
    fixture = isolation_fixture
    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
            InventoryItem.objects.using("app_runtime").create(
                organization_id=fixture.organization_b_id,
                display_name="Forbidden insert",
                vendor_name="Forbidden vendor",
            )

    assert_insufficient_privilege(captured)


def test_cross_tenant_update_affects_no_rows(isolation_fixture):
    fixture = isolation_fixture
    with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
        updated = (
            InventoryItem.objects.using("app_runtime")
            .filter(pk=fixture.item_b_id)
            .update(display_name="Forbidden update")
        )

    assert updated == 0
    assert InventoryItem.objects.get(pk=fixture.item_b_id).display_name == "Inventory B"


def test_missing_tenant_context_fails_closed(isolation_fixture):
    with pytest.raises(DatabaseError) as captured:
        with transaction.atomic(using="app_runtime"):
            raw_inventory_ids("app_runtime")

    assert_insufficient_privilege(captured)


def test_context_on_default_connection_does_not_unlock_app_runtime(
    isolation_fixture,
):
    fixture = isolation_fixture
    with transaction.atomic(using="default"):
        activate_tenant(fixture.organization_a_id, using="default")
        with pytest.raises(DatabaseError) as captured:
            with transaction.atomic(using="app_runtime"):
                raw_inventory_ids("app_runtime")

    assert_insufficient_privilege(captured)


def test_worker_role_cannot_read_another_tenants_business_rows(isolation_fixture):
    fixture = isolation_fixture
    with tenant_transaction(fixture.organization_a_id, using="worker_runtime"):
        assert current_user("worker_runtime") == "agentledger_worker"
        assert raw_inventory_ids("worker_runtime") == {fixture.item_a_id}


def test_csv_staging_is_tenant_isolated_under_app_role(isolation_fixture):
    fixture = isolation_fixture
    user_model = get_user_model()
    batch_a = ImportBatch.objects.create(
        organization_id=fixture.organization_a_id,
        created_by_id=fixture.user_a_id,
        source_filename="a.csv",
    )
    batch_b = ImportBatch.objects.create(
        organization_id=fixture.organization_b_id,
        created_by_id=fixture.user_b_id,
        source_filename="b.csv",
    )
    ImportRow.objects.create(
        organization_id=fixture.organization_a_id,
        batch=batch_a,
        row_number=2,
    )
    ImportRow.objects.create(
        organization_id=fixture.organization_b_id,
        batch=batch_b,
        row_number=2,
    )

    with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
        assert set(
            ImportBatch.objects.using("app_runtime").values_list("id", flat=True)
        ) == {batch_a.id}
        assert set(
            ImportRow.objects.using("app_runtime").values_list("batch_id", flat=True)
        ) == {batch_a.id}
        assert user_model.objects.using("app_runtime").count() == 2

        with pytest.raises(DatabaseError) as captured:
            with transaction.atomic(using="app_runtime"):
                ImportBatch.objects.using("app_runtime").create(
                    organization_id=fixture.organization_b_id,
                    created_by_id=fixture.user_a_id,
                    source_filename="forbidden.csv",
                )

    assert_insufficient_privilege(captured)


def test_background_jobs_are_tenant_scoped_for_app_runtime(isolation_fixture):
    from apps.jobs.models import BackgroundJob
    from apps.jobs.queue import enqueue_job

    fixture = isolation_fixture

    job_a = enqueue_job(
        organization_id=fixture.organization_a_id,
        job_type=BackgroundJob.Type.RISK_REASSESSMENT,
        payload={"tenant": "A"},
    )
    enqueue_job(
        organization_id=fixture.organization_b_id,
        job_type=BackgroundJob.Type.REPORT_GENERATION,
        payload={"tenant": "B"},
    )

    with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
        visible_ids = set(
            BackgroundJob.objects.using("app_runtime").values_list("id", flat=True)
        )

    assert visible_ids == {job_a.id}


def test_app_runtime_cannot_insert_background_job_for_another_tenant(
    isolation_fixture,
):
    from apps.jobs.models import BackgroundJob

    fixture = isolation_fixture

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
            BackgroundJob.objects.using("app_runtime").create(
                organization_id=fixture.organization_b_id,
                job_type=BackgroundJob.Type.RISK_REASSESSMENT,
                payload={"forbidden": True},
            )

    assert_insufficient_privilege(captured)


def test_app_runtime_has_no_background_job_update_authority(isolation_fixture):
    from apps.jobs.models import BackgroundJob
    from apps.jobs.queue import enqueue_job

    fixture = isolation_fixture

    job = enqueue_job(
        organization_id=fixture.organization_a_id,
        job_type=BackgroundJob.Type.RISK_REASSESSMENT,
        payload={"tenant": "A"},
    )

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
            BackgroundJob.objects.using("app_runtime").filter(pk=job.id).update(
                priority=1
            )

    assert_insufficient_privilege(captured)


def test_worker_runtime_can_claim_across_tenants_without_tenant_context(
    isolation_fixture,
):
    from apps.jobs.models import BackgroundJob
    from apps.jobs.queue import claim_next_job, enqueue_job

    fixture = isolation_fixture

    first_job = enqueue_job(
        organization_id=fixture.organization_a_id,
        job_type=BackgroundJob.Type.RISK_REASSESSMENT,
        payload={"tenant": "A"},
        priority=10,
    )
    second_job = enqueue_job(
        organization_id=fixture.organization_b_id,
        job_type=BackgroundJob.Type.REPORT_GENERATION,
        payload={"tenant": "B"},
        priority=20,
    )

    first_claim = claim_next_job(
        "worker-rls",
        using="worker_runtime",
    )
    # Report execution now requires active owner-bound entitlement. Global
    # queue visibility alone cannot bypass that gate.
    assert claim_next_job("worker-rls", using="worker_runtime") is None
    from conftest import grant_core_entitlement

    grant_core_entitlement(
        get_user_model().objects.get(pk=fixture.user_b_id),
        Organization.objects.get(pk=fixture.organization_b_id),
    )
    with connections["worker_runtime"].cursor() as cursor:
        cursor.execute(
            "SELECT app_private.core_work_allowed(%s), status, "
            "available_at <= clock_timestamp(), locked_by "
            "FROM public.background_jobs WHERE id=%s",
            [fixture.organization_b_id, second_job.id],
        )
        admission = cursor.fetchone()
    assert admission == (True, "queued", True, None), admission
    second_claim = claim_next_job(
        "worker-rls",
        using="worker_runtime",
    )

    assert first_claim is not None
    assert second_claim is not None

    assert first_claim.id == first_job.id
    assert first_claim.organization_id == fixture.organization_a_id

    assert second_claim.id == second_job.id
    assert second_claim.organization_id == fixture.organization_b_id


def test_worker_queue_scope_does_not_unlock_business_table_scope(
    isolation_fixture,
):
    from apps.jobs.models import BackgroundJob
    from apps.jobs.queue import enqueue_job

    fixture = isolation_fixture

    enqueue_job(
        organization_id=fixture.organization_a_id,
        job_type=BackgroundJob.Type.RISK_REASSESSMENT,
        payload={"tenant": "A"},
    )
    enqueue_job(
        organization_id=fixture.organization_b_id,
        job_type=BackgroundJob.Type.REPORT_GENERATION,
        payload={"tenant": "B"},
    )

    queue_organizations = set(
        BackgroundJob.objects.using("worker_runtime").values_list(
            "organization_id",
            flat=True,
        )
    )

    assert queue_organizations == {
        fixture.organization_a_id,
        fixture.organization_b_id,
    }

    with tenant_transaction(fixture.organization_a_id, using="worker_runtime"):
        assert raw_inventory_ids("worker_runtime") == {fixture.item_a_id}


def test_report_artifacts_are_tenant_isolated_and_runtime_immutable(
    isolation_fixture,
    legacy_snapshot_factory,
):
    fixture = isolation_fixture

    make_snapshot = legacy_snapshot_factory

    def make_report(
        organization_id,
        user_id,
        snapshot,
        sequence,
        identifier,
        organization_name,
    ):
        return Report.objects.create(
            organization_id=organization_id,
            assessment_snapshot=snapshot,
            sequence=sequence,
            identifier_year=2026,
            report_identifier=identifier,
            organization_display_name=organization_name,
            created_by_id=user_id,
        )

    snapshot_a = make_snapshot(
        fixture.organization_a_id,
        fixture.user_a_id,
        "artifact-a",
    )
    snapshot_b = make_snapshot(
        fixture.organization_b_id,
        fixture.user_b_id,
        "artifact-b",
    )
    snapshot_app_insert = make_snapshot(
        fixture.organization_a_id,
        fixture.user_a_id,
        "artifact-app-insert",
    )
    snapshot_worker_insert = make_snapshot(
        fixture.organization_a_id,
        fixture.user_a_id,
        "artifact-worker-insert",
    )
    snapshot_cross_tenant = make_snapshot(
        fixture.organization_b_id,
        fixture.user_b_id,
        "artifact-cross-tenant",
    )

    report_a = make_report(
        fixture.organization_a_id,
        fixture.user_a_id,
        snapshot_a,
        910001,
        "AL-2026-910001",
        "RLS Firm A",
    )
    report_b = make_report(
        fixture.organization_b_id,
        fixture.user_b_id,
        snapshot_b,
        910002,
        "AL-2026-910002",
        "RLS Firm B",
    )
    report_app_insert = make_report(
        fixture.organization_a_id,
        fixture.user_a_id,
        snapshot_app_insert,
        910003,
        "AL-2026-910003",
        "RLS Firm A",
    )
    report_worker_insert = make_report(
        fixture.organization_a_id,
        fixture.user_a_id,
        snapshot_worker_insert,
        910004,
        "AL-2026-910004",
        "RLS Firm A",
    )
    report_cross_tenant = make_report(
        fixture.organization_b_id,
        fixture.user_b_id,
        snapshot_cross_tenant,
        910005,
        "AL-2026-910005",
        "RLS Firm B",
    )

    artifact_a = ReportArtifact.objects.create(
        organization_id=fixture.organization_a_id,
        report=report_a,
        assessment_snapshot=snapshot_a,
        object_key=build_pdf_object_key(
            organization_id=fixture.organization_a_id,
            assessment_snapshot_id=snapshot_a.id,
            report_id=report_a.id,
        ),
        content_type="application/pdf",
        sha256="a" * 64,
        size_bytes=100,
    )

    artifact_b = ReportArtifact.objects.create(
        organization_id=fixture.organization_b_id,
        report=report_b,
        assessment_snapshot=snapshot_b,
        object_key=build_pdf_object_key(
            organization_id=fixture.organization_b_id,
            assessment_snapshot_id=snapshot_b.id,
            report_id=report_b.id,
        ),
        content_type="application/pdf",
        sha256="b" * 64,
        size_bytes=200,
    )

    # ------------------------------------------------------------
    # App role: Tenant A can read only Tenant A.
    # Tenant B remains hidden even with its exact UUID/object key.
    # ------------------------------------------------------------

    with pytest.raises(
        DatabaseError, match="Authenticated user context is not set"
    ) as missing_identity:
        with tenant_transaction(fixture.organization_a_id, using="app_runtime"):
            list(
                ReportArtifact.objects.using("app_runtime").values_list("id", flat=True)
            )
    assert_insufficient_privilege(missing_identity)

    with (
        identity_transaction(fixture.user_a_id, using="app_runtime"),
        tenant_transaction(fixture.organization_a_id, using="app_runtime"),
    ):
        visible_ids = set(
            ReportArtifact.objects.using("app_runtime").values_list(
                "id",
                flat=True,
            )
        )

        assert visible_ids == {artifact_a.id}

        assert (
            not ReportArtifact.objects.using("app_runtime")
            .filter(id=artifact_b.id)
            .exists()
        )

        assert (
            not ReportArtifact.objects.using("app_runtime")
            .filter(object_key=artifact_b.object_key)
            .exists()
        )

    # ------------------------------------------------------------
    # App role: INSERT is denied.
    # ------------------------------------------------------------

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(
            fixture.organization_a_id,
            using="app_runtime",
        ):
            ReportArtifact.objects.using("app_runtime").create(
                organization_id=fixture.organization_a_id,
                report_id=report_app_insert.id,
                assessment_snapshot_id=snapshot_app_insert.id,
                object_key=build_pdf_object_key(
                    organization_id=fixture.organization_a_id,
                    assessment_snapshot_id=snapshot_app_insert.id,
                    report_id=report_app_insert.id,
                ),
                content_type="application/pdf",
                sha256="c" * 64,
                size_bytes=300,
            )

    assert_insufficient_privilege(captured)

    # ------------------------------------------------------------
    # App role: UPDATE is denied.
    # ------------------------------------------------------------

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(
            fixture.organization_a_id,
            using="app_runtime",
        ):
            ReportArtifact.objects.using("app_runtime").filter(id=artifact_a.id).update(
                size_bytes=999
            )

    assert_insufficient_privilege(captured)

    # ------------------------------------------------------------
    # App role: DELETE is denied.
    # ------------------------------------------------------------

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(
            fixture.organization_a_id,
            using="app_runtime",
        ):
            ReportArtifact.objects.using("app_runtime").filter(
                id=artifact_a.id
            ).delete()

    assert_insufficient_privilege(captured)

    # ------------------------------------------------------------
    # Worker role: Tenant A can read Tenant A and insert a new
    # artifact inside Tenant A.
    # ------------------------------------------------------------

    with tenant_transaction(
        fixture.organization_a_id,
        using="worker_runtime",
    ):
        assert set(
            ReportArtifact.objects.using("worker_runtime").values_list(
                "id",
                flat=True,
            )
        ) == {artifact_a.id}

        worker_artifact = ReportArtifact.objects.using("worker_runtime").create(
            organization_id=fixture.organization_a_id,
            report_id=report_worker_insert.id,
            assessment_snapshot_id=snapshot_worker_insert.id,
            object_key=build_pdf_object_key(
                organization_id=fixture.organization_a_id,
                assessment_snapshot_id=snapshot_worker_insert.id,
                report_id=report_worker_insert.id,
            ),
            content_type="application/pdf",
            sha256="d" * 64,
            size_bytes=400,
        )

        assert worker_artifact.organization_id == fixture.organization_a_id

    # ------------------------------------------------------------
    # Worker role remains tenant-scoped after its legitimate INSERT.
    # ------------------------------------------------------------

    with tenant_transaction(
        fixture.organization_a_id,
        using="worker_runtime",
    ):
        assert set(
            ReportArtifact.objects.using("worker_runtime").values_list(
                "id",
                flat=True,
            )
        ) == {
            artifact_a.id,
            worker_artifact.id,
        }

        assert (
            not ReportArtifact.objects.using("worker_runtime")
            .filter(id=artifact_b.id)
            .exists()
        )

        assert (
            not ReportArtifact.objects.using("worker_runtime")
            .filter(object_key=artifact_b.object_key)
            .exists()
        )

    # ------------------------------------------------------------
    # Worker role: UPDATE remains denied.
    # ------------------------------------------------------------

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(
            fixture.organization_a_id,
            using="worker_runtime",
        ):
            ReportArtifact.objects.using("worker_runtime").filter(
                id=artifact_a.id
            ).update(size_bytes=999)

    assert_insufficient_privilege(captured)

    # ------------------------------------------------------------
    # Worker role: DELETE remains denied.
    # ------------------------------------------------------------

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(
            fixture.organization_a_id,
            using="worker_runtime",
        ):
            ReportArtifact.objects.using("worker_runtime").filter(
                id=artifact_a.id
            ).delete()

    assert_insufficient_privilege(captured)

    # ------------------------------------------------------------
    # Worker role: Tenant A cannot INSERT Tenant B metadata even
    # while holding Tenant B's exact organization/report/snapshot IDs.
    # ------------------------------------------------------------

    with pytest.raises(DatabaseError) as captured:
        with tenant_transaction(
            fixture.organization_a_id,
            using="worker_runtime",
        ):
            ReportArtifact.objects.using("worker_runtime").create(
                organization_id=fixture.organization_b_id,
                report_id=report_cross_tenant.id,
                assessment_snapshot_id=snapshot_cross_tenant.id,
                object_key=build_pdf_object_key(
                    organization_id=fixture.organization_b_id,
                    assessment_snapshot_id=snapshot_cross_tenant.id,
                    report_id=report_cross_tenant.id,
                ),
                content_type="application/pdf",
                sha256="e" * 64,
                size_bytes=500,
            )

    assert isinstance(captured.value, DatabaseError)
    assert isinstance(captured.value.__cause__, psycopg.errors.RaiseException)
    assert "report artifact report does not exist" in str(captured.value)

    assert not ReportArtifact.objects.filter(
        report_id=report_cross_tenant.id,
    ).exists()
